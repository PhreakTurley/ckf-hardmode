# `vendor/`: maintainer-only pinned BepInEx input

This folder is needed only for a full player release. A source build of
`CKFHardMode.dll`, the Data Dump plugin or the config editor does not use it.
`scripts/make_release.py` copies this tree into the player zip unchanged and
refuses to build without it.

## What goes here

    vendor/BepInEx-6.0.0-be.785/
        .doorstop_version
        doorstop_config.ini
        winhttp.dll
        dotnet/                 the CoreCLR runtime doorstop loads
        BepInEx/core/…
        BepInEx/patchers/

Download `BepInEx-Unity.IL2CPP-win-x64-6.0.0-be.785.zip` from <https://builds.bepinex.dev/projects/bepinex_be> and extract its contents directly into `BepInEx-6.0.0-be.785/`, not into a subfolder of it.

`make_release.py` requires the files in `VENDOR_REQUIRED`. It also reads `doorstop_config.ini` and checks that the runtime paths it names (`dotnet/`) exist, because without them the zip installs but BepInEx cannot load (`doorstop_wants`).

## The pin

`BE_BUILD` and `BE_COMMIT` in `scripts/make_release.py`:

    6.0.0-be.785
    6abdba47eeebe08552282e7a58ef0f4a9ab60b62

The script reads both values out of `BepInEx/core/BepInEx.Core.dll`, not from the directory name, so renaming a different build to match the pin still fails. BepInEx BE builds get renumbered and rebuilt, so the commit hash is what identifies the source.

## What must not be here

`BepInEx/config/`, `BepInEx/cache/`, `BepInEx/interop/`, `BepInEx/unity-libs/` and anything under `BepInEx/plugins/` (`VENDOR_FORBIDDEN_PREFIXES`). These are player state or generated files, and BepInEx recreates all of them on first launch. A tree copied out of a live install instead of unpacked from the zip contains them, and `make_release.py` refuses it. `unity-libs/` in particular is generated for one Unity version, so shipping it would tie the release to that version.

## Changing the pin

1. Edit `BE_BUILD` and `BE_COMMIT`.
2. Unpack the new build here.
3. Re-run the end-to-end test on a clean install before shipping.
