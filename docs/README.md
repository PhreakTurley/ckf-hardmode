# Find the project documentation

Use this index to choose the authoritative page for a task. Start with the architecture map, then open the subsystem or mechanic page that owns your question. Code and the live configuration take precedence when prose is stale.

## Start here

| Goal | Read first |
|---|---|
| Understand the four project areas and their boundaries | [Project architecture](architecture.md) |
| Install, dump, edit, test, build, or release | [Workflow](workflow.md) |
| Prepare and publish a public release | [Release playbook](release-playbook.md) |
| Plan a move to first-party data modding | [First-party modding atlas](first-party-modding-atlas.md) |
| Check open work and decisions | `TASKS.md` |
| Avoid a known failure mode | [Gotchas](gotchas.md) |
| Find a configuration field or default | [Generated configuration reference](config-reference.md) |

`config-reference.md` is generated from `schema/*.schema.json`. Never edit it by hand.

## Start a new agent task

For a maintainer checkout, use this sequence before editing:

1. Read `AGENTS.md` completely
2. Run `git status --short` and treat every existing change as someone else's work
3. Read the [architecture map](architecture.md)
4. Read the relevant section of `TASKS.md`
5. Open the owning subsystem or mechanic page from this index
6. Re-read the exact source or live file immediately before editing it

Re-derive counts and file states from the current tree. A handoff, old log, or another agent's report is not a measurement.

## Work on a component

| Component | Scope | Primary guide |
|---|---|---|
| Hard Mode | Shipped BepInEx plugin, table rules, and gameplay subsystems | [Hard Mode guide](../mods/CKFHardMode/README.md) |
| Data Dump | Private table dumper, traces, and diagnostic probes | `mods/CKFDataDump/README.md` |
| Config editor | Schema-driven local editor for the live config | [Config editor guide](../gui/README.md) |
| Schema | Config declarations, defaults, controls, and invariants | [Schema format](../schema/SCHEMA-FORMAT.md) |
| Release packaging | Player archive templates and pinned BepInEx input | [Release templates](../release/README.md), [vendor tree](../vendor/README.md) |

Hard Mode and Data Dump are independent plugins. Both inspect game types through `BepInEx/interop/CoreRPG_v1.dll`, but they share no code or configuration.

## Change data rules

| Task | Reference |
|---|---|
| Understand rule selection, operation order, curves, or indexing | [Rule engine](rule-engine.md) |
| Edit direct CSV or TSV table overlays | [Overlay format](overlays.md) |
| Insert and serve a cloned row | [Cloning rows](cloning-rows.md) |
| Identify the table and domain key for a value | [Table reference](tables.md) |
| Change enemy stats, gear, or roster data | [Tune enemies](tuning-enemies.md) |
| Compare faction roster slots | [Enemy faction parity](enemy-faction-parity.md) |
| Add a Harmony patch | [Patching rules](patching-rules.md) |

Always run pointer validation before launching a configuration that changes IDs or clones.

## Research a game system

| System | Owning page |
|---|---|
| Power levels, progression, mission caps, and difficulty sliders | [Power level](power-level.md) |
| Mission payment, experience, Trust, and reward overrides | [Mission rewards](mission-rewards.md) |
| Global `RuleModel` constants | [Game constants](game-constants.md) |
| Fatigue and its three-tier trait track | [Character fatigue](character-fatigue.md) |
| Unplayed-mission penalties | [Mission elapse penalty](mission-elapse-penalty.md) |
| Save writes for credits and character bars | [GameDb write surface](gamedb-write-surface.md) |
| Enemy turn behavior and observed planner traces | [Enemy AI](enemy-ai.md) |
| Security tally, levels, and card decks | [Security escalation](escalation.md) |
| Mid-mission reinforcement data | [Reinforcements](reinforcements.md) |
| Loot tables and V-Chip parts | [Loot](loot.md) |
| Limit-break trait rows | [Limit-break traits](limit-break-traits.md) |
| Talent tally values and special-code weights | [Talent values and special codes](talent-value-specialcodes.md) |
| Armour family reconstruction | [Armour groups](armour-groups.md) |
| Optional low-level Stun Club attack bonus | [Stun Club](stunclub.md) |

Mechanic pages separate observed results from explanations. Preserve their evidence tags and citations when editing them.

## Know what is private

The public repository includes Hard Mode, the GUI, schemas, release templates, selected build scripts, and the docs in this directory.

The following paths are maintainer-only unless `.gitignore` explicitly changes:

- `mods/CKFDataDump/`
- `overlays/`
- `tests/`
- `sheets/` and `Logs/`
- `AGENTS.md` and `TASKS.md`
- `openspec/`
- the unpacked tree under `vendor/`

Do not copy private measurements or mutable tuning into public docs without checking whether the owning public page should contain them.

## Keep documentation maintainable

- Put each fact in one owning page and link to it elsewhere
- Cite source members instead of line numbers where possible
- Treat the live config as mutable; never describe its current values as shipped defaults
- Derive declarations from schemas or source, not from a dump
- Replace correction histories with the current fact
- Put open work in `TASKS.md`, not in handoff or session-note files
