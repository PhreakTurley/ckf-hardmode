# CKF Hard Mode

In the interest of full transparency all of the code and much of the text you can read was written by an LLM. All design and tuning choices were made by me.

The mod is a BepInEx 6 (IL2CPP) plugin for *Cyber Knights: Flashpoint*.

The mod has several features. Most of them can be turned on or off individually:
1. Talent rebalance (buffs and nerfs), plus game rule tweaks that generally make the game harder
2. Missions can now generate at Power Level 11-20, if your difficulty settings put them that high. Enemies' stats and gear will continue to scale up to PL 20.
3. Greater freedom in tweaking the game's own difficulty modifiers (4x prices, 400% XP gain, etc.). You can easily grow this further.
4. Mission rewards overhauled: PL gain per mission has changed to get teams to around PL 9-10 at the end of retirement. Pure Combat missions give more money/XP. Pure hacking missions generate less PL.
5. New mechanic: Fatigue. Mercenaries might end up "Running Empty" (rolled vs Wound Resist), reducing their Initiative and XP gain for several days. If they run a mission while Running Empty, they'll be "Off-Duty" for several days.
6. New mechanic: Guaranteed pay. Skipping a mission will still deduct credits roughly equal to what you'd have paid them for it. If the mission was for a Contact one of your mercs like, they'll take bonus Stress for ignoring their friend.

Every number it uses is in a config file, editable through the GUI editor that ships with it. And if you don't like a mechanic, just turn it off with the included GUI.

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
