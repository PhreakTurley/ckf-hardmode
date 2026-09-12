# Documentation index

The plugin sources, `schema/*.schema.json` and the overlay CSVs are the sources
of truth. These files explain how the game works and where a lever lives; when
one disagrees with the code, the code wins.

## Getting a change into the game

| I want to… | Read |
|---|---|
| Install, dump the data, edit, test | [`workflow.md`](workflow.md) |
| Know what every setting does | [`config-reference.md`](config-reference.md) (generated) or run `python gui/serve.py` |
| Avoid something that has already failed | [`gotchas.md`](gotchas.md) |
| Add, remove or change a config key | [`../schema/SCHEMA-FORMAT.md`](../schema/SCHEMA-FORMAT.md) |
| Check the live config against the schema | `python schema/check_schema.py --game "<game dir>"` |

## Making changes

| I want to… | Read |
|---|---|
| Write or debug a rule in `ckf.hardmode.rules.json` | [`rule-engine.md`](rule-engine.md) |
| Make enemies harder | [`tuning-enemies.md`](tuning-enemies.md), then [`../overlays/README.md`](../overlays/README.md) |
| Understand the overlay CSV format | [`overlays.md`](overlays.md) |
| Add a row the game does not ship | [`cloning-rows.md`](cloning-rows.md) |
| Write a Harmony patch without crashing the game | [`patching-rules.md`](patching-rules.md) |

## How the game works

| Subject | File |
|---|---|
| Which table controls what, and its key column | [`tables.md`](tables.md) |
| Global constants — cover, heat, caps, story pacing | [`game-constants.md`](game-constants.md) |
| What a mission awards: Team PL, contact PL, money, XP | [`progression.md`](progression.md) |
| How one payout is assembled, term by term | [`mission-rewards.md`](mission-rewards.md) |
| Enemy difficulty and the Power Level 10 ceiling | [`power-and-progression.md`](power-and-progression.md) |
| What drops, and where V-Chip parts come from | [`loot.md`](loot.md) |
| Taking a character out of action after missions | [`character-fatigue.md`](character-fatigue.md) |
| Punishing a mission that expires unplayed | [`mission-elapse-penalty.md`](mission-elapse-penalty.md) |
| Writing credits, Stress or Discontent onto a save | [`gamedb-write-surface.md`](gamedb-write-surface.md) |
| Mid-mission reinforcements (read off the data, never observed firing) | [`reinforcements.md`](reinforcements.md) |
| Giving the collapsed Guard / adaptive variants their own armour again | [`armour-groups.md`](armour-groups.md) |

Build instructions live with the code:
[`../mods/CKFHardMode/README.md`](../mods/CKFHardMode/README.md).
The config editor is described in [`../gui/README.md`](../gui/README.md).

`CKFDataDump`, referenced by name in some of these docs and in code comments as
the tool that produced a measurement, is a separate internal diagnostic plugin
and is not part of this repo.

## The things that bite most often

Full list in [`gotchas.md`](gotchas.md). These four account for most lost time:

1. **Match rows on the domain ID, not `Id`.** Most models inherit an `Id` that
   reads `-1`. The real key is `WeaponId`, `ArmorId`, `MonsterTypeId`.
2. **Two power levels, not three.** Team Power Level is the sum over your mission
   log, not a stored counter. `PowerLevelUnscaled` is that sum floored at mission
   generation and drives rewards; `PowerLevel` is
   `round((teamPowerLevel + BasePowerLevelOffset) × PowerLevelScalar)` at full
   precision and drives enemies. Rounded, not truncated.
3. **Enemy gear numbers live in the overlay CSVs in
   `BepInEx\config\ckf.hardmode.d\`, not `rules.json`.** Overlays
   load last and win. Player gear is the opposite — it stays a rule, prefixed
   `PLAYER`.
4. **A pointer at a row that does not exist is a black screen**, and the game's
   exception never reaches the log. `scripts/validate_rules.py` catches it.
