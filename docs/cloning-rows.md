# Cloning rows: id policy and serving paths

Which id a clone should be inserted under, which reader paths serve a clone and
how far each is proven, and how spawn-pool clones are filtered. Clone syntax is
in [`rule-engine.md`](rule-engine.md#clone-syntax) (JSON) and
[`overlays.md`](overlays.md#clone-lines) (`_clone` lines); failure modes are in
[`gotchas.md`](gotchas.md).

The enemy gear ladders already exist as clone lines in
`ckf.hardmode.d/ArmorModel.csv` and `WeaponModel.csv`. Which id each tier uses
is in [`gear-blocks.md`](../overlays/_reference/gear-blocks.md); check there
before adding a tier. Why PL 11–20 needs clones is in
[`tuning-enemies.md`](tuning-enemies.md).

Use this page only after deciding that an existing row cannot represent the new
tier. For syntax, use `rule-engine.md` or `overlays.md`; for the id and reader
path, use this page.

## Choosing the id

The game is still being updated. A clone must sit where the developers would not
put something, so that removing the mod restores stock content and a future patch
does not collide with an id the mod took. In order of preference:

1. **A developer slot named for the purpose.** `WeaponId` 20010 and 20011 ship
   as "Guard Rifle Lvl11" / "Lvl12", identical to Lvl10 and referenced by no
   shipped monster. Such a row can be edited in place with no clone. The test is
   "named for the thing you want", not "unreferenced".
2. **The free tail of the source row's own family block**, where the family has
   room after it and nothing else starts there. The shipped ladders already used
   these tails for Guard Rifle (`20012`+), Guard Shotgun (`22010`+), AI Standard
   Bullpup (`23040`–`23049`; Corp SMG starts at `23050`), Guard Standard armour
   (`22010`+) and Sniper Guard armour (`22106`+).
3. **The reserved range, `900000` and up**, when the family sits inside a wider
   block the developers would extend themselves. Guard Sniper's shipped tier-10
   weapon is ScopeTek Headshot (`6016`), a player weapon inside the `6001`–`6023`
   sniper block; `6024`+ is where a new player sniper would go. The same holds
   for Monokill (`5016`) in `5001`–`5022`. `MonsterGroupMemberModel` ids run
   `1`–`570` with no gaps, so every spawn-pool clone goes here.
   `RowClone` treats any `set` of an id at or above `900000` that no clone
   declares as an Error (`RowClone.ReservedFrom`).

Not free space:

- **Unreferenced rows are not spare rows.** `WeaponId` 23097–23099 are developer
  work in progress. The list of 74 "unreferenced" `EffectModel` rows is
  unproven: the scan that produced it did not check
  `SecurityDeckCardModel.CardEffectId`, which references `65001`–`65005`. Do not
  repurpose any row from that list until the scan is re-run across every table
  holding an effect id; clone into the reserved range instead.
- **Read ids from the current dump**, never from `Aug21Sheets/`, which is stale
  and has put a wrong id in a config before.

Every weapon in `20000`–`23999` is enemy gear, but ids outside that band include
both player gear and enemy exceptions [measured]. Use the canonical partition in
[`player-vs-enemy-gear.md`](../overlays/_reference/player-vs-enemy-gear.md), not
one broad id predicate.

## Serving paths

`RowClone` hooks every reader that returns the table's row, on every database
that declares one. A table is not owned by one database: `WeaponModel`'s
materializer is on `DataDb`, but `GameDb` declares its own `ReadWeapon(long)`
returning the same content model, and a mission reads enemy gear through that
one. When adding a table, check both.

| Table | Readers | State |
|---|---|---|
| `WeaponModel` | `DataDb.ReadWeapon`, `GameDb.ReadWeapon` | [closed] Cloned tiers served; missions load. |
| `ArmorModel` | `DataDb.ReadArmor` (no other reader returns a content `ArmorModel`) | [closed] Cloned tiers served on mission reload. |
| `MonsterGroupMemberModel` | `DataDb.ReadMonsterGroupMembersByGroup(monsterGroupId, factionId, powerLevel, secLevel)` | [closed] End to end, and at scale: Run68 offered 751 clones across 13 groups to one call and served the 4 that passed both tests. See below. |
| `MonsterTypeModel` | `DataDb.ReadMonsterType`, `ReadMonsterTypeByPowerGroupId` | Open. The list reader is live during encounter building; clone serving on it is unexercised. |
| `MonsterTalentModel` | `DataDb.ReadMonsterTalents(monsterTalentGroup, powerLevel)` | Open. Unexercised. |
| `EffectModel` | `DataDb.ReadEffect` | Open. Unexercised. |
| `MonsterGroupModel` | `DataDb.ReadMonsterGroups`, `GameDb.ReadMonsterGroupsByGroup` | Open. Unexercised. |

What the game derives from a `MonsterSpawnModel` or `MonsterGroupModel` id it
has never seen is unknown [unverified].

Clones are built lazily, on the first read that needs one:

```
RowClone: built  ArmorModel ArmorId 22017 from 22009 — ... 50 -> 80
RowClone: served ArmorModel ArmorId 22017 from ReadArmor
```

`built` without `served` means the row exists and nothing reaches it. No line at
all means nothing asked for it.

## Spawn pools

A cloned `MonsterGroupMemberModel` row is served into a filtered list, so
`RowClone` decides whether it joins a roll; the game's SQL is inside the
encrypted database and cannot be read. With `serveOn: auto` two tests apply:

- **Provenance:** the list already contains the source row.
- **Gate map** (`RowClone.GatesPass`), matched by parameter name:

| Reader | Checked against the clone's columns |
|---|---|
| `ReadMonsterGroupMembersByGroup/4` | `monsterGroupId` = `MonsterGroupId`; `powerLevel` in `MinPowerLevel`–`MaxPowerLevel`; `secLevel` in `MinSecLevel`–`MaxSecLevel` |
| `ReadMonsterTypeByPowerGroupId/1` | `PowerGroupId` |
| `ReadMonsterTalents/2` | `MonsterTalentGroup`; `powerLevel` in `MinPowerLevel`–`MaxPowerLevel` |

A band bound of 0 is an open end. Any other filtered reader gets provenance only,
logged once.

`factionId` is not in the map, so faction filtering rests on provenance. One
data point: `ReadMonsterGroupMembersByGroup(40000, 4, 18, 0)` asked for faction 4
and returned 8 rows that all carry `Faction` 0, so the argument is not a plain
equality filter on that column [measured]. Whether 0 means "any" is
[unverified].

A clone inherits its source's gates. Member 292 carries `MaxPowerLevel` 5, so it
is absent from a PL 18 call, and every clone of it was rejected there with
"source row 292 is not in this list" [measured]. Clone a row that is present in
the calls you care about, and set the gates explicitly:

```json
"as": { "MonsterGroupMemberId": 900007, "MonsterType": 1100,
        "MinPowerLevel": 11, "MaxPowerLevel": 0, "WeightedRoll": 5 }
```

When provenance fails, the log prints the clone's own gate columns next to the
rejection.

### At scale, and the gate map is exact [closed]

Run68, one Warner-Braun mission at scaled PL 18. The reader was offered 751
clones and took 4:

```
RowClone list: ReadMonsterGroupMembersByGroup(40000, 4, 18, 0) returned 12 row(s)
  — 917018: SERVED; 917118: SERVED; 917218: SERVED; 930072: SERVED;
    916001: source row 242 is not in this list [MonsterGroupId=25100 ...]; +745 more
```

Three facts fall out, all [measured]:

- **The band gate is exact.** Two test clones of the same group differed only in
  band: `930071` at PL 4–10 and `930072` at PL 11–20. At PL 18 the first was
  built and never served, the second served. `RowClone.GatesPass` models the
  game's own SQL filter correctly.
- **One clone per power level works.** `917018` is the PL 18 member of a
  twenty-clone ladder (`917010`–`917019`, each `MinPowerLevel` = `MaxPowerLevel`
  = its own level). Exactly one was served.
- **Provenance carries the rest.** The other 747 were rejected by name against
  their own gate columns, not silently dropped.

The 12 rows returned are 8 shipped plus 4 clones, and the roll matched the
weights: WB FireCOM held 5400 of 6700 and took 8 of the 10 spawns.

### The whole chain [closed]

A cloned member row carrying PowerGroup 300 at `WeightedRoll` 100 was served into
`ReadMonsterGroupMembersByGroup(40000, 4, 18, 0)`, and then:

```
MonsterTypeModel[310] PL 11 ... MonsterTypeModel[319] PL 20   <- Guard Bladesman ladder
RowClone: served WeaponModel WeaponId 900001 from ReadWeapon  <- its cloned blade
RowClone: served ArmorModel ArmorId 22207 from ReadArmor      <- its cloned armour
```

PowerGroup 300 is not a member of group 40000 in the shipped data, so the cloned
row was the only route into that roll. The mission spawned almost exclusively
Guard Bladesmen. So: cloned member → pool → weighted roll → spawn → cloned weapon
and armour resolved on the spawned enemy.

"Served" is not "rolled". `served ... into ReadMonsterGroupMembersByGroup` means
offered to the roll; an archetype of that PowerGroup being read means the roll
took it. At `WeightedRoll` 5 the first was seen without the second, which is why
the confirming test used 100.

## Extend at the tail, or rebuild in the reserved range

For a family the developers add in a patch, or a new spawn-pool member, the
choice is who owns PL 1–10:

- **Extend at the tail.** Leave the shipped rows and add tiers after them. The
  developers' PL 1–10 balance stands, their retunes reach players, and removing
  the mod is a clean revert. Right when the shipped ladder only needs to
  continue.
- **Rebuild in the reserved range.** Own all twenty tiers: no seam at PL 10, but
  the developers' numbers no longer reach those enemies. Right when a family
  ships too few rows to extend; ADAPTIVE, Heavy and Drone Infantry armour went
  this way (`901000`–`901079`).

Targets from the shipped ladders: across PL 1–10 weapon damage rises about 1.6x
and armour about 1.75x [measured]. For percentage columns use `gapFrom`
([`rule-engine.md`](rule-engine.md#gapfrom)) and see
[`tuning-enemies.md`](tuning-enemies.md#armour).

## Validate a clone

Before launch, validate the enabled file set from the repository root:

```text
python scripts\validate_rules.py --game "<game root>" --dump "<dump dir>" --enabled-set
```

Resolve every `ERROR`, especially `clone source missing`, `id collision` and
`dangling pointer`. After launch, read `LogOutput.log` for both `RowClone:
built` and `RowClone: served`. `built` alone proves construction, not that a
reader returned the clone; `served` into a spawn-pool list proves eligibility,
not that the weighted roll selected it. The full test sequence and log paths are
in [`workflow.md`](workflow.md).

## Related

- [`rule-engine.md`](rule-engine.md)
- [`overlays.md`](overlays.md)
- [`reinforcements.md`](reinforcements.md)
