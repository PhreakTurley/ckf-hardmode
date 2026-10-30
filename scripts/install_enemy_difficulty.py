"""Verify and hand off Enemy Difficulty sources and prepared Workshop payload.

Never publishes, activates a mod, edits metadata, or changes a save. Both
destination folders must already exist and be explicitly supplied.
"""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from uuid import uuid4

from export_enemy_difficulty import PROJECT
from verify_enemy_difficulty import verify


def digest(data):
    return hashlib.sha256(data).hexdigest()


def require_steam_install(workshop):
    """A manually created directory is not an installed Steam Workshop item."""
    appid, itemid = workshop.parent.name, workshop.name
    if not appid.isdecimal() or not itemid.isdecimal():
        raise ValueError(f"Expected workshop/content/<appid>/<itemid>: {workshop}")
    manifest = workshop.parents[2] / f"appworkshop_{appid}.acf"
    try:
        tokens = re.findall(r'"((?:\\.|[^"\\])*)"|([{}])', manifest.read_text(encoding="utf-8-sig"))
        index = 0

        def object_value(nested=False):
            nonlocal index
            result = {}
            while index < len(tokens):
                text, brace = tokens[index]
                index += 1
                if brace == "}":
                    if not nested:
                        raise ValueError("Unexpected closing brace")
                    return result
                if brace or index >= len(tokens):
                    raise ValueError("Missing key/value")
                value, delimiter = tokens[index]
                index += 1
                if delimiter == "{":
                    result[text] = object_value(True)
                elif delimiter:
                    raise ValueError("Missing value")
                else:
                    result[text] = value
            if nested:
                raise ValueError("Unclosed object")
            return result

        root = object_value()["AppWorkshop"]
        installed = root.get("WorkshopItemsInstalled", {})
        if not isinstance(installed, dict):
            raise ValueError("WorkshopItemsInstalled is not an object")
    except (OSError, KeyError, ValueError) as exc:
        raise ValueError(f"Could not establish Steam installation from {manifest}: {exc}") from exc
    if itemid not in installed:
        raise ValueError(f"Steam has not registered Workshop item {itemid} as installed. "
                         "Subscribe to your own item and let Steam finish downloading before Local Install. "
                         "Creating its folder or copying SQL alone does not register it.")
    return {"manifest": str(manifest), "appid": appid, "itemid": itemid}


def install(project, uploader, workshop):
    for path in (uploader, workshop):
        if not path.is_dir():
            raise ValueError(f"Create the destination first: {path}")
    require_steam_install(workshop)
    receipt = json.loads((project / "review/SOURCE.json").read_bytes())
    for name, expected in receipt["source_inputs"].items():
        if digest(Path(name).read_bytes()) != expected:
            raise ValueError(f"Export input moved; regenerate first: {name}")
    source = project / "source_content/enemy-difficulty.json"
    if digest(source.read_bytes()) != receipt["parser_source_sha256"]:
        raise ValueError("Parser source differs from the validated export")
    copies = [
        (project / "source_content/stories.manifest", uploader / "source_data/stories.manifest"),
        (source, uploader / "source_data/enemy-difficulty.json"),
    ]
    for name in ("data.sql", "en-US.json"):
        src = project / "parser_prepared/_data" / name
        copies += [(src, uploader / "upload_content/_data" / name), (src, workshop / "_data" / name)]
    verified_sources = {src: src.read_bytes() for src, _ in copies}
    verify(project / "parser_prepared/_data/data.sql")
    for name, expected in receipt["source_inputs"].items():
        if digest(Path(name).read_bytes()) != expected:
            raise ValueError(f"Authoring input moved during verification: {name}")
    for src, content in verified_sources.items():
        if src.read_bytes() != content:
            raise ValueError(f"Prepared file moved during verification: {src}")
    staged = []
    for src, dest in copies:
        data = verified_sources[src]
        expected = (dest.stat().st_mtime_ns, digest(dest.read_bytes())) if dest.exists() else None
        dest.parent.mkdir(parents=True, exist_ok=True)
        temp = dest.with_name(dest.name + ".stage-" + uuid4().hex)
        temp.write_bytes(data)
        if digest(temp.read_bytes()) != digest(data):
            raise ValueError(f"Staged copy differs: {temp}")
        staged.append((src, dest, temp, data, expected))
    # Recheck the complete batch immediately before the first commit.
    for src, dest, temp, data, expected in staged:
        current = (dest.stat().st_mtime_ns, digest(dest.read_bytes())) if dest.exists() else None
        if current != expected or src.read_bytes() != data:
            raise ValueError(f"File moved before handoff: {dest}")
    results = []
    for src, dest, temp, data, expected in staged:
        current = (dest.stat().st_mtime_ns, digest(dest.read_bytes())) if dest.exists() else None
        if current != expected:
            raise ValueError(f"File moved before commit: {dest}")
        os.replace(temp, dest)
        if digest(dest.read_bytes()) != digest(data):
            raise ValueError(f"Handoff readback differs: {dest}")
        results.append({"path": str(dest), "bytes": len(data), "sha256": digest(data)})
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=PROJECT)
    parser.add_argument("--uploader-project", type=Path, required=True)
    parser.add_argument("--workshop-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(install(args.project, args.uploader_project.resolve(), args.workshop_dir.resolve()), indent=2))
