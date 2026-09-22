# Understand the project architecture

This page explains how the four project areas fit together, which files own each declaration, and what a change can affect. Read it before changing code or configuration. Use the subsystem pages for implementation details and the workflow for commands.

## Start with the four components

| Component | Purpose | Runtime status | Primary source |
|---|---|---|---|
| Hard Mode | Applies table edits and gameplay subsystems | Shipped and normally enabled | `mods/CKFHardMode/` |
| Data Dump | Captures tables, traces methods, and runs diagnostic probes | Private diagnostic plugin; normally disabled | `mods/CKFDataDump/` |
| Config editor | Edits and validates the live Hard Mode configuration | Local Python server or frozen executable | `gui/` |
| Release pipeline | Builds the player archive and checks its inputs | Maintainer-only full build | `scripts/make_release.py`, `release/`, `vendor/` |

Hard Mode and Data Dump are independent BepInEx 6 IL2CPP plugins. They use different assemblies, plugin identifiers, and configuration files. Neither plugin calls the other.

## Follow the configuration flow

```text
schema/*.schema.json
        |
        +--> scripts/gen_binds.py --------> mods/CKFHardMode/Plugin.Binds.g.cs
        +--> scripts/gen_cfg_template.py -> release/ckf.hardmode.cfg.in
        +--> scripts/gen_docs.py ---------> docs/config-reference.md
        |
        +--> gui/serve.py + gui/app.html
                     |
                     v
game/BepInEx/config/ckf.hardmode.cfg
game/BepInEx/config/ckf.hardmode.d/*
                     |
                     v
             CKFHardMode.dll
```

The schema owns configuration declarations, defaults, editor controls, and invariants. Generated outputs must agree with it. Do not hand-edit `Plugin.Binds.g.cs`, `release/ckf.hardmode.cfg.in`, or `docs/config-reference.md`.

The game installation contains the only tuning copy. The repository does not contain a default or backup copy of `BepInEx\config`. The editor modifies that live copy, and the release builder packages it.

## Understand Hard Mode startup

`Plugin.Load` is the composition root:

1. `Slices.Init` binds the master switch and every slice switch
2. The master switch can stop startup before patches are installed
3. `Defaults.Install` reports missing loose files without creating them
4. `ConfigDoc.Init` reads the settings slices and reports layout problems
5. A mixed pre-4.0 and current layout stops the entire plugin
6. `ModelRules.Init` loads table overlays, lever sheets, and clone rules
7. Independent subsystems initialize behind their own switches

The plugin reads configuration once per process. Relaunch the game after any configuration edit. Rebuild only after a C# change.

`ModelRules` is the parent gate for content slices. When it is off or fails to initialize, table overlays, lever sheets, clone rules, and the generated Team Power Level label do not apply.

Read the [Hard Mode subsystem guide](../mods/CKFHardMode/README.md), [rule engine reference](rule-engine.md), and [overlay format](overlays.md) before changing this path.

## Understand Data Dump coverage

Data Dump has two kinds of work:

- **Sweeps and mission probes**: gated by `[General] Enabled`
- **Diagnostics and specialized probes**: controlled by their own settings and initialized before the general gate

`[General] Enabled = false` does not disable `TraitProbe`, `WriteProbe`, `ElapseProbe`, member inspection, method tracing, or ID constant collection. `TraitProbe` and `WriteProbe` can modify a save.

A dump or trace is evidence only for the path and sampling moment it covered. Check `_coverage.csv`, `_readers.csv`, probe completeness flags, caps, and hook timing before interpreting silence.

Read the private `mods/CKFDataDump/README.md` before running the plugin.

## Understand editor saves

The editor is schema-driven. `gui/app.html` renders the model returned by `gui/serve.py`; the page does not own configuration names or validation rules.

`App.api_save` performs this sequence:

1. Reject files changed since the page loaded
2. Build proposed bytes without writing them
3. Validate a temporary configuration tree
4. Write neighbor temporary files and an atomic save journal
5. Rename the files into place and remove the journal
6. Validate the live directory again

The editor writes directly to the live configuration and keeps no backup. A lever-sheet edit is checked for syntax and row identity, but its columns are not described by the schema.

Read the [config editor guide](../gui/README.md) and [schema format](../schema/SCHEMA-FORMAT.md) before changing editor behavior.

## Choose the correct source of truth

| Question | Authority |
|---|---|
| Which config keys exist and what are their defaults? | `schema/*.schema.json` |
| How does the plugin behave? | C# source under `mods/CKFHardMode/` |
| What tuning is active on this machine? | Live game `BepInEx\config` |
| What did the shipped game data contain when captured? | Data Dump output under `sheets/raw` or the configured output directory |
| What is known about a game mechanic? | The owning mechanics page with evidence tags and citations |
| What work remains? | `TASKS.md` |
| What failed before? | `docs/gotchas.md` |
| How is a release assembled? | `scripts/make_release.py` and `docs/workflow.md` |

Code comments and prose can become stale. Re-derive a count, version, or file set from its declaration before repeating it.

## Map changes to required checks

| Change | Required follow-up |
|---|---|
| Live tuning only | Validate the live config, relaunch, and exercise the affected game path |
| Schema | Regenerate binds, cfg template, and config reference; run schema and editor checks |
| Hard Mode C# | Build the plugin, run relevant offline gates, and provide the build command for the machine |
| GUI Python or HTML | Run source self-tests, JavaScript self-tests, and frozen-executable tests for release work |
| Table pointers or clones | Run `scripts/validate_rules.py` against a complete dump before launch |
| Save-writing subsystem | Review the write path before running it, then test with the approved save procedure |
| Release inputs | Run the release self-test and full release gate against a snapshot of the live config |

The [workflow](workflow.md) contains the exact commands and the [gotchas](gotchas.md) explain expected failures.

## Respect public and private boundaries

The repository uses `.gitignore` as an allowlist. New files under published folders are public by default. Research data, logs, test harnesses, Data Dump, OpenSpec material, and the unpacked BepInEx distribution remain private unless the allowlist changes deliberately.

The public checkout can build Hard Mode and the config editor. A full release also needs the maintainer's live configuration, built plugin, and pinned private vendor tree.
