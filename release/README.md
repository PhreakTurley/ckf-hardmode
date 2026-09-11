# `release/` — the three templates that are rendered into the player zip

`scripts/make_release.py` renders every `*.in` in here, substituting three
placeholders and refusing on any it does not fill:

| | |
|---|---|
| `@VERSION@` | `<Version>` out of `mods/CKFHardMode/CKFHardMode.csproj` |
| `@BE_BUILD@` | `BE_BUILD` in `scripts/make_release.py` |
| `@BE_COMMIT@` | `BE_COMMIT` in the same place |

The output is CRLF and UTF-8. Where each one lands is the `TEMPLATES` table in
`make_release.py`, not the filename: the two text files go to the root of the
zip under the same name without the suffix, and `ckf.hardmode.cfg.in` goes to
`BepInEx/config/ckf.hardmode.cfg`. A `*.in` here that `TEMPLATES` does not name
is rendered by nothing and reaches no player; `--selftest` fails on one.

The rest of what ships under `BepInEx/config/` is copied byte for byte from
`mods/CKFHardMode/defaults/` and `overlays/` — that is the `CONFIG_FILES` table
in the same script, and nothing in here.

## `README.txt.in`

The install instructions. The pinned BepInEx build appears twice in it and is
a placeholder both times, because a README that names a build the zip does not
contain is worse than one that names none.

**The "WHAT IT IS" paragraph is the one to rewrite before a ModDB listing.** It
was drafted from the subsystem names and `openspec/changes/consolidate-config-and-ship/proposal.md`,
not from playing the mod, and it is the only paragraph here that describes
what the mod does rather than how to install it.

## `LICENSE-BepInEx.txt.in`

A header naming the redistributed build, its commit, the source it came from
and the files it covers, then the GNU LGPL 2.1 verbatim.

The licence text is the canonical one. From the repo root:

```
python -c "import hashlib;b=open('release/LICENSE-BepInEx.txt.in','rb').read();t=b[b.index(b'                  GNU LESSER'):];print(len(t),hashlib.md5(t).hexdigest())"
```

`26530 4fbd65380cdd255951079008b364516c`. Do not reflow it, and do not let a
placeholder into it — the substitution runs over the whole file, and
`make_release.py` renders it to CRLF, which is why the hash is taken here on
the `.in` and not on what ships.

BepInEx is LGPL-2.1 [checked against github.com/BepInEx/BepInEx, 2026-09-04];
`CKFHardMode.dll` and `CKF-Config-Editor.exe` are separate works and the header
says so.

## `ckf.hardmode.cfg.in`

The master switch, `[General] Enabled`, rendered to
`BepInEx/config/ckf.hardmode.cfg`. It is a template rather than a copied file
because its header comment names the plugin version.

BepInEx writes this file itself on the first launch, from the one key
`Plugin.cs` binds, and rewrites it on every launch after that. Shipping it only
means that first launch is not what creates it. That is also why it is CRLF:
`render` folds every template to CRLF and BepInEx writes CRLF, so what ships
and what BepInEx would write are the same bytes.

Keep it byte-for-byte what BepInEx produces. It is not a place to add keys —
BepInEx preserves a key it did not bind (`docs/gotchas.md`), so an invented one
would sit in every player's config being read by nothing.

## Why these are not written by the script

They are prose, they get edited, and a diff of a template is readable. The
version numbers in them are not, which is what the placeholders are for.
`make_release.py --selftest` asserts each file exists, renders, and carries
what only it can carry — the pin in the licence header, the version and the one
key in the cfg.
