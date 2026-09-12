# `vendor/` — the pinned BepInEx, unpacked

`scripts/make_release.py` copies this tree into the player zip verbatim and
refuses to build without it.

## What goes here

    vendor/BepInEx-6.0.0-be.785/
        .doorstop_version
        changelog.txt
        doorstop_config.ini
        winhttp.dll
        BepInEx/core/…
        BepInEx/patchers/

Download `BepInEx-Unity.IL2CPP-win-x64-6.0.0-be.785.zip` from
<https://builds.bepinex.dev/projects/bepinex_be> and extract its **contents**
straight into `BepInEx-6.0.0-be.785/` — not into a subfolder of it.

## The pin, and why it is two things

`BE_BUILD` and `BE_COMMIT` in `scripts/make_release.py`:

    6.0.0-be.785
    6abdba47eeebe08552282e7a58ef0f4a9ab60b62

Both are read out of `BepInEx/core/BepInEx.Core.dll`, not out of the directory
name, so a tree renamed to match the pin still fails. BE builds are renumbered
and rebuilt; the commit is what identifies the source.

This is the build in the live install and therefore the one every run recorded
in `openspec/changes/consolidate-config-and-ship/tasks.md` was made against.
[measured, `BepInEx/LogOutput.log` line 1-2, 2026-09-04]

## What must not be in here

`BepInEx/config/`, `BepInEx/cache/`, `BepInEx/interop/`, `BepInEx/unity-libs/`
and anything under `BepInEx/plugins/`. All of them are a player's own state or
machine-generated, BepInEx recreates every one on first launch, and
`make_release.py` refuses on any of them by path. They are what you get if you
build this tree by copying out of a live install instead of unpacking the zip,
which is why the check exists.

`unity-libs/` in particular is generated for one Unity version on first launch.
Shipping it would pin the mod to the Unity build it was generated against.

## Changing the pin

Edit `BE_BUILD` and `BE_COMMIT`, unpack the new build here, and re-run the
end-to-end test on a clean install before shipping the result. The refusal
message says the same thing.
