# `defaults/` — three of the config files the release zip ships

Three of the eight files that go into the release zip under `BepInEx/config/`.
The zip is what puts them on disk: extracting it over the game folder is the
install, and `Defaults.cs` only checks afterwards that all eight arrived.

| File | Ships to | Read by |
|---|---|---|
| `ckf.hardmode.json` | `BepInEx/config/ckf.hardmode.json` | `ConfigDoc`, then all nine sections |
| `ckf.hardmode.selfcheck.csv` | `BepInEx/config/ckf.hardmode.selfcheck.csv` | `SelfCheck.Load` |
| `ckf.hardmode.d/MissionPowerLevelModel.generated.json` | `BepInEx/config/ckf.hardmode.d/` | `Overlays.LoadJson` |

Four more — `ckf.hardmode.rules.json` and the three overlay CSVs — are copied
into the zip straight out of `overlays/`, which is already the source of truth
for the rule set. Copying them here would create a second copy that
`merge_overlays.py` and `validate_rules.py` do not compare against. There is one
copy of each file in this repository and that is deliberate. The eighth,
`ckf.hardmode.cfg`, is rendered from `release/ckf.hardmode.cfg.in` so its header
carries the release version.

`CONFIG_FILES` in `scripts/make_release.py` is the list of what ships and where
it lands in the zip; `Expected` in `Defaults.cs` is the list of what has to be
on disk at launch. Change one and you have to change the other — nothing derives
either list.

**Correction, 2026-09-07.** This file's title was "what the DLL writes on a
first run", and it opened: "Three of the seven files `CKFHardMode.dll` embeds.
`Defaults.cs` writes any of the seven that is absent from `BepInEx/config/` and
never touches one that is there." Both halves were true until today. The seven
`<EmbeddedResource>` entries were removed from `CKFHardMode.csproj` and
`Defaults.cs` stopped writing: **the DLL embeds nothing, and nothing in the mod
puts a config file on disk.** The old sentence about `CKFHardMode.csproj` being
"the list of all seven with the resource name each one gets" went with them —
that project file embeds no resources at all now.

## Why the directory is shaped like `BepInEx/config`

So the existing tools can be pointed at it. These two are gates:

```
python schema\check_schema.py --config "mods\CKFHardMode\defaults" --no-cfg
python scripts\gen_teampl_labels.py --config "mods\CKFHardMode\defaults" --check
```

The first validates every declared field, range, section name and invariant in
the shipped document. The second proves the shipped mirror still agrees with the
shipped `teampl` section — the mirror is generated from `teampl.override`, so
the two can drift, and a player has no Python to regenerate it with.

`--no-cfg` exists for this directory. `check_schema.py` normally reads
`ckf.hardmode.cfg` alongside the document; this directory has no `.cfg` because
the shipped one is rendered from `release/ckf.hardmode.cfg.in` at release time
and does not live here.

## `ckf.hardmode.json` is byte-for-byte what `merge_sidecars.py` renders

`json.dumps(doc, indent=2, ensure_ascii=False) + "\n"`, UTF-8, LF, no BOM.
`gui/serve.py --selftest` has a check asserting a no-op save writes zero bytes,
so the GUI has to round-trip that shape exactly.

**Correction, 2026-09-07.** This paragraph used to say "`Defaults.Upgrade`
reproduces that exact shape when it rewrites the document … a document the DLL
rewrote in a different shape would fail it". `Defaults.Upgrade` no longer
exists: the key-fill pass and everything else `Defaults.cs` wrote were removed
today, so **no C# in this mod rewrites `ckf.hardmode.json`** and the only
writers left are `merge_sidecars.py` and the GUI's save path.

## Where these values came from

The five sections that had a 2.x sidecar (`elapse`, `fatigue`, `missions`,
`rewardcurve`, `teampl`) are leaf-for-leaf the 2.13.0 shipped sidecars — 1062
leaves, none differing, checked against `_config-baseline-2.13.0/`. The four
sections Phase 3 created (`modelrules`, `powerlevel`, `selfcheck`, `difficulty`)
carry the values their `.cfg` keys shipped with, which is what the 2.13.0 `.cfg`
in that same baseline holds. [measured, 2026-09-03]

`_config-baseline-2.13.0/` could not supply this file itself: it predates both
merges, so it has five sidecars, a 22-key `.cfg` and no merged document at all.
