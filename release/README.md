# `release/`: maintainer-only player-zip templates

This folder is not part of the public source-build path. It holds three text
templates that the private release workflow renders into the player zip. To
build only the plugin or run the editor from source, use the component READMEs.
For a full release, use [`../docs/workflow.md`](../docs/workflow.md).

## Rendering

`make_release.py:render` fills three placeholders. It refuses if any `@NAME@` is left unfilled, and it writes the output as UTF-8 with CRLF line endings.

| Placeholder | Source |
|---|---|
| `@VERSION@` | `<Version>` in `mods/CKFHardMode/CKFHardMode.csproj` |
| `@BE_BUILD@` | `BE_BUILD` in `make_release.py` |
| `@BE_COMMIT@` | `BE_COMMIT` in `make_release.py` |

Where each file goes in the zip is set by the `TEMPLATES` table in `make_release.py`, not by the filename:

| Template | Path in zip |
|---|---|
| `README.txt.in` | `README.txt` |
| `LICENSE-BepInEx.txt.in` | `LICENSE-BepInEx.txt` |
| `ckf.hardmode.cfg.in` | `BepInEx/config/ckf.hardmode.cfg` |

`make_release.py --selftest` fails on any `*.in` in this folder that `TEMPLATES` doesn't list. It also fails if `README.txt.in` or `LICENSE-BepInEx.txt.in` is missing. Checks that need a missing template report NOT RUN.

The release requires the 16 paths in `CONFIG_FILES`, copied byte for byte from
the live config or `--config DIR`, plus the rendered
`BepInEx/config/ckf.hardmode.cfg`. Those 17 paths match
`Defaults.Expected`. The directory sweep also ships any additional `.csv`,
`.tsv` or `.json` in `ckf.hardmode.d/`. None of those loose files comes from
this folder.

## `README.txt.in`

The player's install instructions. `@VERSION@` appears in the title line. The pinned BepInEx build appears once, as `@BE_BUILD@`, never written out literally.

## `LICENSE-BepInEx.txt.in`

This file has two parts: a header naming the redistributed BepInEx build, its commit, the source it came from and the files it covers, followed by the GNU LGPL 2.1 text verbatim. Don't reflow the licence text or put a placeholder in it, because substitution runs over the whole file. The selftest checks that the rendered file contains `BE_BUILD`, `BE_COMMIT` and `LESSER GENERAL PUBLIC LICENSE`. `CKFHardMode.dll` and `CKF-Config-Editor.exe` are separate works, and the header says so.

To confirm the licence text is still the canonical one, run this from the repo root. It must print `26530 4fbd65380cdd255951079008b364516c`. The hash is taken on the `.in` file because rendering converts line endings to CRLF.

```
python -c "import hashlib;b=open('release/LICENSE-BepInEx.txt.in','rb').read();t=b[b.index(b'                  GNU LESSER'):];print(len(t),hashlib.md5(t).hexdigest())"
```

## `ckf.hardmode.cfg.in`

The starting `ckf.hardmode.cfg`: `[General] Enabled` and one `[Slices]` toggle per slice, at their declared defaults. It must match what BepInEx itself writes for the plugin.

- It is generated. Never edit it by hand. Run `python scripts/gen_cfg_template.py` (maintainer-only; not published) to regenerate it from `schema/*.schema.json`, using the key set from `gen_binds.py`. `--check` fails if the template has drifted, and `make_release.py --selftest` runs that check.
- The selftest also checks that the rendered file starts with `## Settings file was created by plugin CKF Hard Mode v<version>`, uses CRLF, contains `[General]` / `Enabled = true`, and has more than one key under `[Slices]`.
- It is a template, not a copy of the live `.cfg`, for two reasons: its header carries the release version, and the zip must ship the default toggles rather than whatever David has switched off.
- Don't add keys by hand. BepInEx keeps keys it didn't bind, so an invented key would stay in every player's config with nothing reading it.

## Related

- [`../gui/README.md`](../gui/README.md): the editor exe that ships beside these files
- [`../docs/workflow.md`](../docs/workflow.md)
