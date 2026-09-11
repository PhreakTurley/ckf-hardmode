# CKF Hard Mode

A BepInEx 6 (IL2CPP) plugin for *Cyber Knights: Flashpoint*. A difficulty
overhaul: declarative row edits, the Power Level ceiling, Team PL awards,
mission rewards, fatigue, and the mission-elapse penalty. Every number it uses
is in a config file, editable through the GUI editor that ships with it.

Not made by Trese Brothers Games and they cannot support it.

## Get the mod

Download the latest zip from this repo's
[Releases page](../../releases/latest). Extract it into the game's install
folder (the one holding `CyberKnights.exe`) — full instructions are in the
zip's `README.txt`.

## Alternate tuning

Releases also carry separate, smaller zips — alternate sets of the config
files under `BepInEx/config/` — for players who want a different balance
profile without redownloading the whole mod (BepInEx and the .NET runtime are
most of the main zip's size). See [`tuning/README.md`](tuning/README.md) for
what a tuning variant contains and how to install one.

## Repo layout

```
mods/CKFHardMode/   the plugin source
schema/             the config schema — one file per subsystem; source of
                    truth for the config, gen_binds.py, and gen_docs.py
overlays/           enemy gear and archetype numbers, as CSV, plus the rule set
gui/                the config editor (serve.py + app.html)
release/            the templates make_release.py renders into the player zip
scripts/            gen_binds.py, gen_docs.py, gen_teampl_labels.py,
                    make_release.py (builds the release zip)
docs/               mechanics references and the workflow — start at
                    docs/README.md
tuning/             alternate config sets, packaged as extra release assets
```

`schema/*.schema.json` is the source of truth for the config: `gen_binds.py`
emits `mods/CKFHardMode/Plugin.Binds.g.cs` and `gen_docs.py` emits
`docs/config-reference.md`. Neither is hand-edited.

## Building a release

```
python scripts/make_release.py
```

Builds the config editor exe, renders the `release/*.in` templates, and zips
everything into `dist/CKF-Hard-Mode-<version>.zip`. `--selftest` runs the
script's own checks without producing a zip. See `release/README.md` for what
each template is and where it lands.

`dist/` is gitignored — the built zip and any tuning-variant zips are
distributed as GitHub Release assets, not committed here.

## Start here

- **Install, dump, edit, test** — [`docs/workflow.md`](docs/workflow.md)
- **Every setting, what it does and what it defaults to** —
  [`docs/config-reference.md`](docs/config-reference.md), or run the GUI:
  `python gui/serve.py`
- **Traps, dead ends and settings that silently do nothing** —
  [`docs/gotchas.md`](docs/gotchas.md)
- **Everything else** — [`docs/README.md`](docs/README.md) is the index

## License

The mod's own source (`mods/`, `schema/`, `gui/`, `scripts/`) has no license
file attached yet — all rights reserved by default. The zip bundles a
redistributed BepInEx build under LGPL-2.1; see `release/LICENSE-BepInEx.txt.in`
for that license's text and what it covers.
