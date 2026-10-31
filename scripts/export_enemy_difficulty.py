"""Export enemy armor and armor lookups to a first-party Workshop data mod.

Reads ArmorModel.csv and only ArmorTypeId from MonsterTypeModel.csv, including
parked .disabled inputs. Rule82.Value is set to 20. Every other official table and enemy
field is outside the write set. Never edits tuning, saves, Workshop metadata or the separate
PL4-20 roster project.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from decimal import Decimal, ROUND_HALF_EVEN
import hashlib
import io
import json
import os
from pathlib import Path
from uuid import uuid4

from static_data import StaticData, DEFAULT_DB, quote

ROOT = Path(__file__).resolve().parents[1]
CONFIG = Path(r"C:\Program Files (x86)\Steam\steamapps\common\Cyber Knights Flashpoint\BepInEx\config\ckf.hardmode.d")
MODKIT = Path(r"C:\Program Files (x86)\Steam\steamapps\common\Cyber Knights Mod Uploader")
PARSER_SCHEMA = MODKIT / "CyberKnightsModkit_Data/StreamingAssets/config.json"
PROJECT = ROOT / "ckf-enemy-difficulty"
KEYS = {"Armor": "ArmorId", "MonsterType": "MonsterTypeId", "Rule": "RuleId"}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encode(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def sql_value(value):
    if value is None:
        return "NULL"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def number(value, kind):
    if value is None or value == "":
        return None if value is None else ""
    if "INT" in kind.upper():
        try:
            return int(Decimal(str(value)).to_integral_value(rounding=ROUND_HALF_EVEN))
        except Exception:
            return str(value)
    if kind.upper() in ("REAL", "FLOAT", "DOUBLE", "NUMERIC"):
        return float(value)
    return str(value)


def csv_bytes(rows, columns):
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue().encode("utf-8")


def guarded_write(path, data, expected=None):
    """Fresh output name, optimistic mtime/hash guard, atomic replace, reread."""
    before = (path.stat().st_mtime_ns, sha(path.read_bytes())) if path.exists() else None
    if expected is not None and before != expected:
        raise ValueError(f"Concurrent change: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = path.with_name(path.name + ".stage-" + uuid4().hex)
    staged.write_bytes(data)
    if staged.read_bytes() != data:
        raise ValueError(f"Staged bytes differ: {staged}")
    current = (path.stat().st_mtime_ns, sha(path.read_bytes())) if path.exists() else None
    if current != before:
        raise ValueError(f"Concurrent change before commit: {path}")
    os.replace(staged, path)
    if sha(path.read_bytes()) != sha(data):
        raise ValueError(f"Written bytes differ: {path}")


def build(data_path=DEFAULT_DB, config_dir=CONFIG, schema_path=PARSER_SCHEMA):
    inputs, stamps = {}, {}

    def read(path):
        path = path.resolve()
        stamp = path.stat().st_mtime_ns
        raw = path.read_bytes()
        if path.stat().st_mtime_ns != stamp:
            raise ValueError(f"Source changed while reading: {path}")
        stamps[path] = stamp, sha(raw)
        inputs[str(path)] = sha(raw)
        return raw

    schema = json.loads(read(schema_path))
    contracts = {t: {f["name"]: f["type"] for f in schema[t]["sql"]["fields"]} for t in KEYS}
    with StaticData(data_path) as db:
        read(db.path)
        read(db.locale_path)
        tables = {}
        for t, key in KEYS.items():
            if schema[t]["sql"]["table"] != t or set(contracts[t]) != {c[1] for c in db.schema[t]}:
                raise ValueError(f"Parser/official SQL column disagreement: {t}")
            tables[t] = {int(r[key]): {c: number(v, contracts[t][c]) for c, v in r.items()}
                         for r in db.read(t + "Model", labels=False)[1]}
        base = {t: {i: dict(r) for i, r in rows.items()} for t, rows in tables.items()}
        statements, locales, ledger, overlay_rows, clone_rows = [], {}, [], {}, {}

        def update(t, identity, values, origin):
            if t == "Rule" and (identity != 82 or set(values) != {"Value"} or values["Value"] != 20):
                raise ValueError("Only Rule82.Value=20 belongs to this export")
            if t == "MonsterType" and set(values) - {"ArmorTypeId"}:
                raise ValueError("Enemy armor export cannot write other MonsterType fields")
            values = {c: v for c, v in values.items() if tables[t][identity][c] != v}
            if values:
                statements.append(f"UPDATE {quote(t)} SET " + ",".join(quote(c) + "=" + sql_value(v) for c, v in values.items())
                                  + f" WHERE {quote(KEYS[t])}={identity};")
                tables[t][identity].update(values)
                ledger.extend({"Table": t, "Id": identity, "Column": c, "Value": v, "Origin": origin} for c, v in values.items())

        def overlay(t):
            filename = t + "Model.csv"
            choices = [p for p in (config_dir / filename, config_dir / (filename + ".disabled")) if p.is_file()]
            if len(choices) != 1:
                raise ValueError(f"Need exactly one active or parked source for {filename}: {choices}")
            path = choices[0]
            reader = csv.DictReader(io.StringIO(read(path).decode("utf-8-sig")))
            if not reader.fieldnames or reader.fieldnames[0] != KEYS[t]:
                raise ValueError(f"Wrong key header: {path}")
            for c in reader.fieldnames:
                if not c.startswith("_") and c not in contracts[t]:
                    raise ValueError(f"Undeclared column/operator {t}.{c}")
            rows, seen = [], set()
            for line, raw in enumerate(reader, 2):
                if not any((v or "").strip() for v in raw.values()):
                    continue
                identity = int(raw[KEYS[t]])
                if identity in seen:
                    raise ValueError(f"Duplicate ({t}, {identity}) in {path}")
                seen.add(identity)
                values = {c: number(v.strip(), contracts[t][c]) for c, v in raw.items()
                          if c != KEYS[t] and not c.startswith("_") and v and v.strip()
                          and (t == "Armor" or c == "ArmorTypeId")}
                source = int(raw["_clone"]) if raw.get("_clone", "").strip() else None
                if t == "MonsterType" and source is not None:
                    raise ValueError(f"MonsterType clones are outside armor-only scope: {identity}")
                rows.append((identity, source, values, f"{path.name}:{line}", raw.get("_comment", "")))
            overlay_rows[t] = rows
            for identity, source, values, origin, _ in rows:
                if source is None:
                    if identity not in base[t]:
                        raise ValueError(f"Overlay update has no official row: ({t}, {identity})")
                    update(t, identity, values, origin)
            for identity, source, values, origin, comment in rows:
                if source is None:
                    continue
                if t != "Armor" or source not in base[t] or identity in tables[t]:
                    raise ValueError(f"Invalid armor clone: ({t}, {identity}) from {source}")
                columns = list(contracts[t])
                assignments = {**values, KEYS[t]: identity}
                expressions = [sql_value(assignments[c]) if c in assignments else quote(c) for c in columns]
                statements.append(f"INSERT OR REPLACE INTO {quote(t)} ({','.join(map(quote, columns))}) SELECT "
                                  + ",".join(expressions) + f" FROM {quote(t)} WHERE {quote(KEYS[t])}={source};")
                tables[t][identity] = {**tables[t][source], **assignments}
                clone_rows.setdefault(t, []).append((identity, source))
                ledger.extend({"Table": t, "Id": identity, "Column": c,
                               "Value": tables[t][identity][c], "Origin": origin} for c in columns)
                family = comment.split(" tier PL ")[0].replace("-", " ").title()
                label = db.locale.get("ArmorName." + str(source), family)
                locales["ArmorName." + str(identity)] = f"{label} (PL {tables[t][identity]['PowerLevel']})"

        if base["Rule"][82]["ConfigName"] != "Max Enemy Power Level":
            raise ValueError("Rule82 no longer declares the enemy ceiling")
        update("Rule", 82, {"Value": 20}, "native enemy ceiling")
        overlay("Armor")
        overlay("MonsterType")
        # Extend only armor lookups to newly shipped ladders. Native weapon,
        # talent and stat fields never enter the assignments.
        groups, ambiguous = defaultdict(dict), set()
        authored_ids = {r[0] for r in overlay_rows["MonsterType"]}
        for row in base["MonsterType"].values():
            pg, pl = row["PowerGroupId"], row["PowerLevel"]
            if pl in groups[pg]:
                ambiguous.add(pg)
            groups[pg][pl] = row
        extensions = []
        for pg, levels in sorted(groups.items()):
            if set(levels) != set(range(1, 21)) or any(r["MonsterTypeId"] in authored_ids for r in levels.values()):
                continue
            if pg in ambiguous:
                raise ValueError(f"Ambiguous full armor ladder: {pg}")
            signature = tuple(levels[p]["ArmorTypeId"] for p in range(1, 11))
            matches = [g for g, lv in groups.items() if set(lv) == set(range(1, 21)) and g not in ambiguous
                       and all(r["MonsterTypeId"] in authored_ids for r in lv.values())
                       and tuple(lv[p]["ArmorTypeId"] for p in range(1, 11)) == signature]
            outcomes = {tuple(tables["MonsterType"][groups[g][p]["MonsterTypeId"]]["ArmorTypeId"] for p in range(11, 21)) for g in matches}
            if len(outcomes) != 1:
                raise ValueError(f"New PowerGroup {pg} has ambiguous/missing authored armor ladder")
            for pl, pointer in zip(range(11, 21), next(iter(outcomes))):
                update("MonsterType", levels[pl]["MonsterTypeId"], {"ArmorTypeId": pointer}, "new official ladder: matched authored armor")
            extensions.append({"PowerGroupId": pg, "Column": "ArmorTypeId", "MatchingAuthoredGroups": matches})
        for identity, row in tables["MonsterType"].items():
            if row["ArmorTypeId"] != base["MonsterType"][identity]["ArmorTypeId"] and row["ArmorTypeId"] not in tables["Armor"]:
                raise ValueError(f"Unresolved authored armor: MonsterType {identity} ArmorTypeId={row['ArmorTypeId']}")
        statement_bytes = ("-- CKF Enemy Difficulty: armor, enemy armor lookups and Rule82=20.\n"
                           + "\n".join(statements) + "\n").encode("utf-8")
        source_bytes = encode({"Metadata": {"StoryKey": "CKFEnemyDifficulty", "StartingId": 900000},
                               "RawSQL": statements, "RawText": {"Generic": locales}})
        summary = {"format": 2, "scope": "Armor rows, MonsterType.ArmorTypeId and Rule82.Value=20",
                   "official_database": str(db.path), "official_database_sha256": inputs[str(db.path)],
                   "configuration_directory": str(config_dir.resolve()), "parser_schema": str(schema_path.resolve()),
                   "source_inputs": inputs, "exporter_sha256": sha(Path(__file__).read_bytes()),
                   "new_ladder_gear_extensions": extensions,
                   "authored_overlay_rows": {t: len(r) for t, r in overlay_rows.items()},
                   "authored_gear_clones": {t: len(r) for t, r in clone_rows.items()},
                   "sql_statements": len(statements), "column_writes": len(ledger),
                   "column_writes_by_table": dict(Counter(r["Table"] for r in ledger)),
                   "locale_entries": len(locales), "parser_source_sha256": sha(source_bytes),
                   "direct_sql_sha256": sha(statement_bytes),
                   "runtime": "Armor-only payload has not been exercised in game."}
        artifacts = {"source_content/stories.manifest": b"# CKF Enemy Difficulty\nenemy-difficulty.json\n",
                     "source_content/enemy-difficulty.json": source_bytes,
                     "prepared/_data/data.sql": statement_bytes,
                     "prepared/_data/en-US.json": encode(locales),
                     "review/SOURCE.json": encode(summary),
                     "review/column-ledger.csv": csv_bytes(ledger, ("Table", "Id", "Column", "Value", "Origin"))}
        db.assert_unchanged()
    for path, (stamp, digest) in stamps.items():
        if path.stat().st_mtime_ns != stamp or sha(path.read_bytes()) != digest:
            raise ValueError(f"Source moved during export: {path}")
    return artifacts, summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DEFAULT_DB)
    parser.add_argument("--config-dir", type=Path, default=CONFIG)
    parser.add_argument("--parser-schema", type=Path, default=PARSER_SCHEMA)
    parser.add_argument("--out", type=Path, default=PROJECT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    artifacts, summary = build(args.data, args.config_dir, args.parser_schema)
    for relative, content in artifacts.items():
        path = args.out / relative
        if args.check:
            if not path.exists() or path.read_bytes() != content:
                raise ValueError(f"Stale artifact: {path}")
        else:
            guarded_write(path, content)
    print(json.dumps({k: summary[k] for k in ("authored_overlay_rows", "authored_gear_clones",
                                            "sql_statements", "column_writes_by_table", "locale_entries")}, indent=2))


if __name__ == "__main__":
    main()
