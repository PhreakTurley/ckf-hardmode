# Cloning rows: id policy and serving paths

How to choose the id a `clone` inserts under, and which serving paths have
actually been exercised.

**The gear ladders are already built** and live as CSV in the live
`BepInEx\config\ckf.hardmode.d\` (`ArmorModel.csv`, `WeaponModel.csv`).

**Enemy gear is an overlay; player gear is a rule.** Overlays load after
`ckf.hardmode.rules.json`, so where the two overlap the overlay wins — an enemy
gear rule added back to `rules.json` still runs and then silently does nothing.
`_reference/gear-tiers.csv` lists every tier and the file that provides it; look
there before writing anything here.

Syntax for `clone` / `as` / `serveOn` is in [`rule-engine.md`](rule-engine.md)
§Clone syntax; overlay `_clone` lines are in [`overlays.md`](overlays.md); the
failure modes are in [`gotchas.md`](gotchas.md); log reading and the validator
are in [`workflow.md`](workflow.md); why PL 11–20 needs any of this is in
[`tuning-enemies.md`](tuning-enemies.md).

---

## 1. Choosing the id

**The game is still being updated. A clone must sit where the developers would
not put something, so that removing this mod's rules restores stock content and
a future patch does not collide with an id we took.** In preference order:

**1. The developer's own next slot, when one exists and is named for the
purpose.** `WeaponId` 20010 and 20011 ship as "Guard Rifle Lvl11" and
"Guard Rifle Lvl12", identical to Lvl10 and referenced by no monster. That is a
slot the developers left for exactly this, so use it with an ordinary rule — no
clone needed.

This is a narrow category. "Unreferenced" is not the test; *named for the thing
you want* is. The 74 unreferenced `EffectModel` rows and `WeaponId` 23097–23099
are **developer work in progress, not free space** — see
[`gotchas.md`](gotchas.md).

**2. The free tail of the source row's own family block.** Enemy families are
laid out with room after them:

| Family | Block | Free tail |
|---|---|---|
| Guard Rifle | `20000`–`20011` | `20012`+ |
| WB Revolver | `21001`–`21010` | `21011`+ |
| Guard Shotgun | `22000`–`22009` | `22010`+ |
| AI Standard Bullpup | `23030`–`23039` | `23040`–`23049` (Corp SMG starts at 23050) |
| Guard Standard armour | `21999`–`22009` | `22010`–`22099` |
| Guard ADAPTIVE armour | `22200`–`22206` | `22207`–`22299` |
| Sniper Guard armour | `22100`–`22105` | `22106`–`22199` |
| Guard Heavy armour | `22300`–`22306` | `22307`–`22399` |

**3. The reserved range `900000`+**, when the family sits inside a wider block
the developers would extend themselves. Guard Sniper's tier-10 weapon is
ScopeTek Headshot (`6016`), a *player* weapon inside the `6001`–`6023` sniper
block; `6024`+ is where a new player sniper would go, so it is not ours to take.
Same for Monokill (`5016`) inside `5001`–`5022`.

`MonsterGroupMemberModel` has no tails at all — ids run `1`–`570` with no gaps —
so every spawn-pool clone uses the reserved range.

**Always check the current dump, never a sheet in `Aug21Sheets/`.** Those are
stale, and reading a weapon id off one has already put a wrong value in a config.
`BepInEx/ckf-dump/<Table>.csv` is written by the live game.

Enemy weapons occupy `20000`+ and player weapons sit below it, and rules band on
that boundary; a clone in the reserved range sits outside both. Whether the
*game* reads anything into that boundary is **unverified**.

---

## 2. What each path rests on

| Table | Serving path | State |
|---|---|---|
| `WeaponModel` | `DataDb.ReadWeapon`, `GameDb.ReadWeapon` | **Closed.** Built and served in Run 35; the mission loads. |
| `ArmorModel` | `DataDb.ReadArmor` — no other reader anywhere returns a content `ArmorModel` | **Closed.** Built and served in Run 36, two families, on a mission reload. |
| `MonsterGroupMemberModel` | `DataDb.ReadMonsterGroupMembersByGroup(monsterGroupId, factionId, powerLevel, secLevel)` | **Closed, end to end** (Run 40). See below. |
| `MonsterTypeModel` | `DataDb.ReadMonsterType`, `ReadMonsterTypeByPowerGroupId` | **Open.** The list reader is confirmed live during encounter building; clone serving on it is unexercised. |
| `MonsterTalentModel` | `DataDb.ReadMonsterTalents(monsterTalentGroup, powerLevel)` | **Open.** Unexercised. |
| `EffectModel` | `DataDb.ReadEffect` | **Open.** Unexercised. |
| `MonsterGroupModel` | `DataDb.ReadMonsterGroups`, `GameDb.ReadMonsterGroupsByGroup` | **Open.** Unexercised. |

**A table is not owned by one database.** `WeaponModel`'s materializer is
declared on `DataDb`, but `GameDb` declares its own `ReadWeapon(long)` returning
the same content model, and that is the one a mission uses for enemy gear.
RowClone hooks every reader returning the row on every database. When adding a
table, check both — this cost a run.

### Spawn pools: what the gate map covers

A cloned `MonsterGroupMemberModel` row is served into a **filtered list**, not
fetched by id, so whether it joins a roll is decided by RowClone, not by the
game's SQL — which is inside the encrypted database and cannot be read. The test
is provenance (the list already contains the source row) plus a hand-built gate
map: `powerLevel` against `MinPowerLevel`/`MaxPowerLevel`, `secLevel` against
`MinSecLevel`/`MaxSecLevel`.

**`factionId` is not in that map** — it was left out rather than guessed at, so
faction filtering currently rests on the provenance test alone. Run 37 gives one
data point: the call `ReadMonsterGroupMembersByGroup(40000, 4, 18, 0)` asked for
faction 4 and returned 8 rows that **all carry `Faction` 0**, so the second
argument is not a plain equality filter on that column [measured]. Whether 0
means "any", or the argument keys off something else entirely, is
**unverified**.

Run 37 also rejected all seven spawn clones with *"source row 292 is not in this
list"*, correctly: member 292 carries `MaxPowerLevel` 5, so it is absent from a
PL 18 call and a clone of it inherits that ceiling. Clone a row that is present
in the calls you care about, and set the gates explicitly in `as`:

```json
"as": { "MonsterGroupMemberId": 900007, "MonsterType": 1100,
        "MinPowerLevel": 11, "MaxPowerLevel": 0, "WeightedRoll": 5 }
```

When provenance fails, the log prints the clone's own gate columns next to the
rejection, which is usually enough to see the cause.

### The whole chain, proven

Run 40 closed it [closed]. A cloned member row carrying PowerGroup 300 at
`WeightedRoll` 100 was served into `ReadMonsterGroupMembersByGroup(40000, 4, 18, 0)`,
and then:

```
MonsterTypeModel[310] PL 11 ... MonsterTypeModel[319] PL 20   <- Guard Bladesman ladder
RowClone: served WeaponModel WeaponId 900001 from ReadWeapon  <- its cloned blade
RowClone: served ArmorModel ArmorId 22207 from ReadArmor      <- its cloned armour
```

PowerGroup 300 is **not** a member of group 40000 in the shipped data, so the
only route into that roll was the cloned row. Zero errors. In the mission
itself: almost exclusively Guard Bladesmen, as the weight demanded.

So the full chain works — **cloned row → pool → weighted roll → spawn → cloned
weapon and armour resolved on the spawned enemy.**

**Served is not rolled.** `served ... into ReadMonsterGroupMembersByGroup` means
offered to the roll; an archetype of that PowerGroup being read means the roll
took it. Run 39 had the first without the second at `WeightedRoll` 5, which is
why the confirming test used 100.

---

## 3. Extend at the tail, or rebuild into the reserved range

What you would come back here for is a family the developers *add* in a patch,
or a spawn-pool member. Two decisions, both settled by whose numbers should own
PL 1-10:

- **Extend at the family tail.** Leave the shipped rows alone and add tiers
  after them. Their balance for PL 1-10 stands, a patch that retunes it reaches
  your players, and removing the mod is a clean revert. Right when the shipped
  ladder is fine and only needs to continue.
- **Rebuild into the reserved range.** Own all twenty tiers. No seam at PL 10,
  no inherited regressions, and families that never had ten tiers get twenty.
  The cost is that the developers' numbers no longer reach those enemies at all.
  Right when a family ships too few rows to extend — ADAPTIVE, Heavy and Drone
  Infantry all went this way.

Two numbers to aim at, from the shipped ladders [measured]: across PL 1-10
weapon damage rises about **1.6x** and armour about **1.75x**. For how to move a
percentage column, see [`rule-engine.md`](rule-engine.md) §`gapFrom` and
[`tuning-enemies.md`](tuning-enemies.md) §3.
