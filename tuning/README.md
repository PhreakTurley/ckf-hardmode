# Alternate tuning

A tuning variant is a replacement set of the files `scripts/make_release.py`
lists in `CONFIG_FILES` as loose config, everything under the player's
`BepInEx/config/` that isn't the master on/off switch:

```
ckf.hardmode.rules.json               overlays/ckf.hardmode.rules.json
ckf.hardmode.d/ArmorModel.csv         overlays/ArmorModel.csv
ckf.hardmode.d/WeaponModel.csv        overlays/WeaponModel.csv
ckf.hardmode.d/MonsterTypeModel.csv   overlays/MonsterTypeModel.csv
ckf.hardmode.json                     mods/CKFHardMode/defaults/ckf.hardmode.json
ckf.hardmode.selfcheck.csv            mods/CKFHardMode/defaults/ckf.hardmode.selfcheck.csv
```

A variant does not have to touch all of them — only the files it changes.
A player installs one by extracting it over their existing
`BepInEx/config/`, the same way the main zip's README describes resetting to
shipped defaults.

## Layout

```
tuning/
├── README.md          this file
└── <variant-name>/
    └── BepInEx/
        └── config/
            ├── ckf.hardmode.rules.json          (if this variant changes it)
            └── ckf.hardmode.d/
                ├── ArmorModel.csv               (if this variant changes it)
                ├── WeaponModel.csv
                └── MonsterTypeModel.csv
```

Mirroring the `BepInEx/config/` path inside the variant folder means "extract
into your game folder" is the entire install instruction, matching the main
zip.

Each `<variant-name>/` gets zipped (`<variant-name>.zip`) and attached to the
same GitHub Release as the main mod zip, as an additional asset — see the repo
root README for the release command. No variant content is checked in here
yet; this is the convention the first one follows.
