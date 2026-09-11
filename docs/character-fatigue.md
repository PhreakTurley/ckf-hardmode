# Mission fatigue — Running Empty → Off-Duty

How the shipped mission-fatigue mechanic works. `mods/CKFHardMode/Fatigue.cs`,
CKFHardMode 2.9.2, `[Fatigue] Enabled` default true.

Settings: `docs/config-reference.md` (Fatigue section), generated from
`schema/*.schema.json`. Traps: `docs/gotchas.md`. Test procedure:
`docs/workflow.md`.

**RUN44–RUN47** mark facts observed in a live save (2026-08-29/30); the rest are
read off `global-metadata.dat`, the interop DLLs' `NativeMethodInfoPtr_*` field
names, the `BepInEx/ckf-dump/` save CSVs and `en-US.json`. **[unverified]** marks
a claim never observed.

---

## 1. The mechanic

Two shipped traits, no custom content, no new save state.

```
  mission completes
         │
         ├── merc was already Running Empty ──► force Off-Duty (no roll)
         │                                       └─► engine stops them being
         │                                           rostered until it expires
         │
         └── merc was clear ──► roll ──► fail ──► Running Empty
                                 │                 └─► still selectable,
                                 └── pass ──► nothing      but −4 Init, −50% XP
```

The player gets one mission of warning. Running Empty does not stop anyone
deploying; deploying anyway earns the lockout. Enforcement is the engine's, off
Off-Duty's `SpecialCode 90 BlockMissions` ("Unwilling to go on any mission
(unless required by mission)"): the mod grants the trait and stops there, never
filtering `ReadGameCharactersAvailableForMission`, and the game keeps its
story-mission override.

**RUN45**: Rhino held 2014 (row 163, `SpecialCode 90` on the row's joined
`EffectData`) and still came back from
`ReadGameCharactersAvailableForMission(1386)` with an aggregate reading
`SpecialCode 0` — consistent with `docs/character-availability.md`, where the
gate is one SQL query over the **character row** with no trait term. Whether the
planning screen blocks above the query, or enforcement reads
`GameCharacterEffect`, is **[unverified]**; nothing in the mod depends on it.

## 2. The two traits

Both are `TraitClass 6` (limit-break temporary traits), `TraitScore -2` (severe
tier), `TraitLevel 1`, each in its **own `TraitGroup`**, so a merc can hold both
at once without a group collision.

| | Running Empty | Off-Duty |
|---|---|---|
| `TraitId` | **2009** | **2014** |
| `TraitGroup` | 2009 | 2014 |
| `EffectTypeId` | 10507 | 10512 |
| Effect name in locale | **"Bloodless"** (not "Running Empty") | "Off-Duty" |
| `EffectClassification` | 12 `MutationTempTrait` | 12 `MutationTempTrait` |
| Effect | `InitBonus -4`, `XpBonus -50` | `SpecialCode 90 BlockMissions`, value 1 |
| Shipped flavour | "Your body is here moving on autopilot, but that is about it." | "You have decided to take a break for a bit and it is not up for debate." |

Off-Duty carries no stat penalty at all; its entire content is SpecialCode 90.
Running Empty's bite is the −50% XP; the −4 Initiative is the combat half.
**2007 Checked Out** (`InitBonus -2`, `XpBonus -33`) is the milder first stage,
selectable through `runningEmpty.traitId` without a rebuild — also `TraitClass 6`
in its own group, so it is legal beside 2014.

The shipped Stress Limit Break grants these for **30 days**, which is where the
default durations come from. 4 turns = 1 day (`RuleModel` 40 `Max Injury Time` =
100 turns, "25 days default"). `EffectSpecialCode.BlockMissions = 90` is
confirmed against `_id_constants.csv`.

**RUN44**, read back off the game's own join on a row the mod inserted:
`id 163 char 6 trait 2009 created 1383 expires 1503 | TraitData yes EffectData
yes (Effect 10507 InitBonus -4 XpBonus -50 SpecialCode 0)`.

**RUN45**: a TraitClass 6 temporary trait reaches the character's stat aggregate.
Panther carried shipped trait 2007 and her `MissionStart` aggregate read
`XpBonus -33`, which can come from nothing else on her (Bubbles read `+4` from
1009 Below the Level 2, Rhino `0` with no XP trait), so Running Empty's
`XpBonus -50` lands the same way. `InitBonus` is not readable this way — the
aggregate carries gear, implants and jobs too.

Traits are processed in `TraitContext.MissionStart`; `MissionVictory` and
`CyberSurgery` are the other two contexts and neither appeared in Run45.

## 3. Trigger — mission, not room

`GameScoreModel` rows for one mission arrive in a fixed order: every
`ScoreTypeId 19 MissionCompleteByCharacter` row, one per deployed merc, then a
single `ScoreTypeId 16 MissionComplete` row with `CharacterId 0` as terminator.
Across the reference save, **92 turns carry a type-16 row and 92 carry type-19
rows, with no orphan on either side**; the shape held on RUN44's four-merc
mission and RUN45's solo hack alike. `ScoreTypeId 20
MissionCompleteByCharacterUnseen` interleaves, is per-character and conditional
on not being spotted (RUN44: char 6 got a 19 and no 20), and is ignored. Type-16
and type-19 rows carry the real game turn; types 15 `AttackKilled` and 18
`SpikeCPU` carry the *mission* turn in `GameTurn`. Rooms do not interfere —
`StartRoom` fires 106 times against those 92 missions and a two-room mission
still produced one `MissionComplete`.

The hook is a postfix on `GameDb.InsertGameScore(GameScoreModel) -> Int64`.
**Phase A**, on `ScoreTypeId == 19`, pushes `CharacterId` onto a pending list;
**Phase B**, on `ScoreTypeId == 16`, resolves the mission from that list and
clears it.

**RUN45: a failed mission writes no score rows at all.** A four-merc mission was
lost on purpose; its last row was `StartRoom`, then `ProcessGameOver
gameOverWin=False`, then the safehouse four turns later. **A lost mission costs
no fatigue**; `applyOnMissionFailure` exists neither as key nor code, and the
defeat-side hook (`View_MissionRoomDefeat_Main.ProcessCharactersAfterDefeat`) is
not built.

**Solo missions are exempt** (David's ruling, 2026-09-10). When Phase B's
roster holds one distinct `CharacterId`, nothing in §4 runs: no roll, no
Off-Duty escalation, no row written, nothing marked resolved. A merc who goes out
alone while Running Empty keeps the first stage and is not locked out. The log
line is `Fatigue: mission complete at turn N with one merc deployed (character
X). Solo missions are exempt`. Offline checks: `tests/fatigue/Part5.cs`.

Nothing is gated on `Status`, which is transient at mission end: RUN44 saw chars
1, 19 and 20 read `Status 12 Extracted` on the victory screen and `Status 1
Active` a few reads later, while on defeat all four read `status=1`. That type 19
means *deployed* rather than *survived and extracted* is **[unverified]**.

## 4. Resolution order

Phase B runs once per mission over the pending `CharacterId` list. The order is
what makes "went out while Running Empty" a clean test with no timestamp
arithmetic and no deploy-time hook.

1. **Read** each merc's traits — `ReadGameCharacterTraitsByCharacter(characterId)`.
2. **Off-Duty pass.** Any merc already holding 2009 gets 2014 for its configured
   duration, no roll. With `offDuty.clearsRunningEmpty` their 2009 row is deleted
   in the same pass, inside the success branch only, so a refused insert cannot
   leave the merc carrying nothing.
3. **Build the roll pool** — deployed mercs holding **neither** 2009 nor 2014.
4. **Roll** each merc in the pool against their own chance (§5).
5. **Clamp** the failure count into `[minAffected, maxAffected]` by margin.
6. **Grant** 2009 to the final failure set.

Because step 2 reads before step 6 writes, no `CreatedTurn` comparison is needed.

**The double-fire guard** is keyed on the completion turn **and the sorted
roster**, so two missions completing on one turn resolve separately, and the
database decides it rather than session memory: every row §6.2 writes is stamped
`CreatedTurn` = the mission's turn, so a first-stage or Off-Duty row at that turn
on any roster merc is that resolution's own evidence. Present means a genuine
second Phase B and the guard blocks; absent means a save load rolled the database
back, and the mission resolves again to the same result through deterministic
rolls. A postfix on `ViewModel_GameManagement.LoadGame` / `.LoadGameSlot` clears
session state on load; both fire on one load (elapse layer, Log16).

## 5. The roll

**Chance.** One percentage per merc per completed mission, read off
`runningEmpty.byPowerLevel` at the mission's power level (§8). The Cyber Knight
uses `runningEmpty.knight.byPowerLevel` where it names a chance, identified by
`GameCharacterModel.IsKnight` — a real boolean column, `True` on character 1 in
the reference save (`CharacterTypeId == 1` is the equivalent test). The Face
never enters this at all: `CharacterTypeId 6` is excluded by the eligibility SQL,
so the Face does not deploy.

**Duration.** `ExpiresTurn = GameTurn + durationDays * 4`, `durationDays` again
off the curve; the Knight's curve overrides it. `durationDays: 0` on an anchor is
refused at load, because `ExpiresTurn` of zero is how the game marks a trait
PERMANENT (`ProcessTraits` filters on `ExpiresTurn != 0`). If no anchor names a
`durationDays` at all, the merc is **not granted the trait** — a row with no
length would be that permanent trait — and both the missing key and the merc it
cost are logged.

**Clamp.** `minAffected` and `maxAffected` are absolute counts applying only to
the Running Empty roll; forced Off-Duty grants are never clamped. Each merc's
margin is their roll minus their own threshold: short of `minAffected`, the
smallest *passing* margins fail; past `maxAffected`, the smallest *failing*
margins are spared. Ranking is by distance from each merc's **own** threshold,
since Wound Resist (§9) makes thresholds differ per merc, and ties break on
character id so a reload reproduces the same set. `minAffected` is capped at pool
size; a curve that names no `maxAffected` means no ceiling, `maxAffected: 0` a
ceiling of zero (zero switches the roll off while leaving escalation running),
and a curve that names no `minAffected` means no floor. The Knight sits inside
the clamp — no `knight.exemptFromClamp` key exists, and RUN47 saw Panther take
2009 like the rest.

**Determinism.** The roll is seeded from `splitmix64(GameTurn, CharacterId)` plus
a constant salt, so the same inputs give the same result however many times the
victory screen is reloaded; `deterministicRolls: false` falls back to unseeded
RNG. **RUN47 verified this against a prediction made before the run**: rolls for
turns 1386-1388 were computed offline in advance, the mission landed on 1388, and
characters 1, 16 and 19 rolled 27, 61 and 97 exactly as predicted.

## 6. Implementation mechanics

### 6.1 The calls and the database instance

All on `RPG.Database.GameDb`: the hook `InsertGameScore(GameScoreModel)`;
`ReadGameCharacterTraitsByCharacter(Int64) -> List<GameCharacterTraitModel>`;
`InsertGameCharacterTrait(GameCharacterTraitModel) -> Int64`;
`DeleteGameCharacterTrait(Int64) -> Int32`; `ReadGameCharacter(Int64)` for
`IsKnight`; and the zero-arg `ReadGameData()` for `GameTurn` / `GameKey`.
`ReadGameCharacter` is the file's one catch that could swallow the Knight — a
rename there makes every merc read `IsKnight 0` and `DisplayName ""` — so it logs
once, naming what that costs.

The postfix is handed the live `GameDb` as `__instance`, used there and never
stored. **RUN44** confirmed the walk for hooks that get no `GameDb` directly:
`__instance` (SaveManager) → `.Dac` (`RPG.Core.GameManagerBase`) →
`RPG.Saving.DataLayer` → `.GameDBI`. `DataLayer` has no static singleton, so
there is no `GameDb` outside a hook (`docs/gotchas.md`).

### 6.2 Building the trait row

`GameCharacterTraitModel` columns:

```
Id, CharacterId, TraitTypeId, OptionId, IsWound, Description, CreatedTurn, ExpiresTurn, IsNew
```

The mod sets `CharacterId`, `TraitTypeId`, `CreatedTurn = GameTurn`,
`ExpiresTurn = GameTurn + days*4`, `IsWound = 0`, `IsNew = 1`, `OptionId = 0`,
`Description = ""`, and leaves `Id` at 0 for the insert to assign and return.
The turn comes off the `GameScoreModel` being inserted, read from the `__args`
model rather than by calling `ReadGameData()`, so `ExpiresTurn` is based on the
same turn the mission's own score rows carry.

**RUN44: use Route A — construct the row.** `GameCharacterTraitModel` has a
public parameterless `.ctor` on both the leaf and `GameCharacterTraitModelBase`;
`Activator.CreateInstance` allocated a usable il2cpp object, the insert returned
id 163, and both readers found it. Borrowing an existing row stays in
`TraitProbe` as a fallback instrument and is not used by the mod.

**RUN44: the joined properties fill themselves in, and the reader decides it.**
`GameCharacterTraitModel` carries `TraitData`, `EffectData` and
`MatrixEffectData` alongside its nine columns. The constructed row went in with
all three null — and so did the row from `ReadGameCharacterTrait(163)`, while
`ReadGameCharacterTraitsByCharacter(6)` returned the *same row* fully joined:

```
built      : id   0  TraitData NULL  EffectData NULL
after-byid : id 163  TraitData NULL  EffectData NULL        <- ReadGameCharacterTrait
after-bychar id 163  TraitData yes   EffectData yes (10507, InitBonus -4, XpBonus -50)
```

Nothing populates the joins by hand, and a trait row's effect is only readable
through the by-character reader, which is what step 1 of §4 uses.

### 6.3 Re-entrancy, durability and expiry

The mod calls `GameDb` methods from inside a `GameDb` postfix, behind the
`reentrant` flag `RowClone.cs` already carries. **RUN45** granted 2014 from
inside the `InsertGameScore` postfix on the type-16 row, through SqlNado while
the game's own insert was still unwinding. **RUN47** ran the whole of §4 that way
over a four-merc roster at turn 1388 — two inserts plus the first-ever
`DeleteGameCharacterTrait`, which returned 1 — with zero errors.

Writes are exactly as durable as the game's: `GameDb` is a live working database
and a save slot is a snapshot of it (`DataLayer.CreateSnapshot` and its `Tmp` /
`FromTmp` / `Safehouse` variants), so an inserted trait persists when the
player's own progress persists and never separately. RUN45 opened on a save that
had lost the whole of Run44 — proved by the score id counter reissuing 3238 — and
the mod's row went with it. The mod does not force a save.

**RUN46** granted 2014 to Rhino at `GameTurn 1386` with `GrantDurationDays = 1`
(`ExpiresTurn 1390`), audited through `ReadGameCharacterTraitsByCharacter(16)`:

| | rows | what it shows |
|---|---|---|
| after the grant | 4 | the row is there |
| after loading a different save slot | 3 | that slot never had it — correct |
| after coming back to the saved slot | 4, `expires 1390` | survived a save and a reload |
| at `GameTurn 1391` | 3 | expired on schedule, one turn past `ExpiresTurn` |

The mod writes the row and sets `ExpiresTurn`; the game's own
`SaveManager.ProcessTraits` handles the rest of its life cycle.

## 7. Save state added: none

Both traits live in `GameCharacterTrait`, a table the game already owns.
`SaveManager.ProcessTraits` runs `SELECT * FROM GameCharacterTrait WHERE
ExpiresTurn != 0 AND ExpiresTurn <= ?` every turn, removes expired rows, and logs
`Timeline.Log.TraitExpired` — *"{trait} has expired from {name} / The temporary
{0} Trait has lapsed and no longer affects {1}."* The mod never ticks and adds no
column, side file or row to any table the game does not already write.
Uninstalling it leaves at most a few live traits, which lapse on schedule.

## 8. Power-level scaling

`chancePercent`, `durationDays`, `minAffected` and `maxAffected` each vary with
the mission's power level. Since **2026-09-07** the curves are the **only** place
they live; see the correction at the end of this section.

The level comes from `GameDb.ReadGameMissionActive() -> GameMissionModel` and its
**`PowerLevel`** column — the effective level, the one `[PowerLevel]` lifts past
the stock ceiling of 10; `PowerLevelUnscaled` is the input to that scaling and is
the wrong column here. Score rows carry no mission identity (`ScoreTargetId 0`,
empty `ScoreKey`), so the level is read at **Phase A**, on the first type-19 row,
while the mission is still active; Phase B retries, and if both fail the level
stays 0 and **every curve returns its lowest anchor** for it. The log says so
once.

**The curve.** Anchors interpolate linearly, rounding away from zero. Each field
walks only the anchors that name it, so a curve can shape the chance across all
twenty levels while stepping the ceiling at three. Below the lowest anchor and
above the highest the nearest anchor holds — a curve is a statement about the
levels it names, not an extrapolation past them.

```jsonc
"byPowerLevel": {
  "1":  { "chancePercent": 10, "minAffected": 0, "maxAffected": 1 },
  "10": { "chancePercent": 25, "minAffected": 0, "maxAffected": 2 },
  "20": { "chancePercent": 40, "minAffected": 1, "maxAffected": 4 }
}
```

A full twenty-row list works identically, and one anchor is a flat value written
as a curve. `offDuty.byPowerLevel` and `offDuty.knight.byPowerLevel` interpolate
`durationDays` by the same precedence — a Knight curve beats the general curve —
and the other three fields mean nothing on an Off-Duty anchor (escalation is not
a roll), so they are warned about by name. Anchors carry the validation the flat
settings used to, including a sweep across PL 1-20 that catches a floor and
ceiling each legal on its own anchor and still crossing between them; validation
runs at load and names the offending key.

### 8.1 The flat settings were removed — 2026-09-07

**What this section used to say**, and what was true until this date: each of the
four values had a flat setting *and* a curve, the curve beat the flat value where
it named a level, the flat value applied where it did not, and — the sentence
that mattered most — *"if both fail the flat values apply and the log says so
once"* for a mission whose `PowerLevel` could not be read. `no block leaves the
flat values in force` was also written here, meaning an omitted `byPowerLevel`
fell back to them.

**David's ruling.** Every flat setting that had a `byPowerLevel` analogue is off
the config surface, because a one-anchor curve at power level 1 does the same
job. The eight: `runningEmpty.chancePercent`, `.durationDays`, `.minAffected`,
`.maxAffected`, `runningEmpty.knight.chancePercent`,
`runningEmpty.knight.durationDays`, `offDuty.durationDays` and
`offDuty.knight.durationDays`.

**Why the unreadable-`PowerLevel` sentence had to change with them.** `Curve()`
used to return "no value" for a `powerLevel` of 0, which is what sent that case
to the flat values; with the flat values gone that would have left the one code
path nobody can control with no answer at all. So the `powerLevel <= 0` guard was
dropped and a 0 now falls into the existing `powerLevel <= lowest anchor` clamp:
an unreadable level takes the **lowest anchor** of each curve. That is what makes
a one-anchor PL 1 curve behave exactly like the flat value it replaces, in every
case including that one. The once-only warning is still logged and now says the
lowest anchor was used.

**What replaces the flat layer as a backstop:** nothing, deliberately, and that
is reported rather than papered over.

- `runningEmpty.byPowerLevel` is **required** while `fatigue.enabled` is true.
  Absent or empty, the config names no chance, no duration and no counts; the
  feature refuses to load and says which block is missing.
- Where a curve names no value for one field, the roll or the write that needed
  it **does not happen and is logged**: no chance means the merc is not rolled
  for, no first-stage `durationDays` means the trait is not granted, no
  `offDuty` `durationDays` means the merc is not escalated and keeps the first
  stage. In each case the alternative would be a trait row with a zero
  `ExpiresTurn`, which is how the game marks a trait PERMANENT. Mercs lost this
  way are counted separately in the mission summary — not folded into "clear",
  which they are not.
- `minAffected` is the one exception: no anchor naming it means **no floor**, a
  legal state, so it takes the named constant `NoMinAffected` (0) and is a
  warning rather than an error.
- `maxAffected` is unchanged: absent has always meant no ceiling.

**Old config files still load.** `Fatigue.cs` refuses any file carrying a key
that maps to no member, so the eight properties were kept and marked
legacy-and-ignored rather than deleted — removing them would have made every
existing player's `ckf.hardmode.json` fail to load. They parse, nothing reads
them, and a file carrying any of them gets one log line at load naming which.
Deleting them from the file changes nothing.

## 9. Wound Resist mitigation

A merc's Wound Resist is subtracted from their chance, **one point per percentage
point**, floored at `woundResist.minChancePercent` (default 5) so nobody is
immune and `minAffected` always has someone to reach for. The floor bounds what
resist takes away and never raises a chance already at or below it, so
`chancePercent: 0` stays 0.

**The stat.** The **Triage Clinic** is `ModuleClassId 18`, module types 71-74,
granting exactly two things: `InjuryTime` -25/-30/-35/-40 and **`WoundRes`**
10/15/20/30 by upgrade level. `WoundRes` is a plain integer column on both
`EffectModel` and `SafehouseModuleModel`.

**`EffectClassification` values are explicit, not declaration order.** Read out
of the metadata `Constant` table:

| | | | | |
|---|---|---|---|---|
| 1 TalentBuff | 2 TalentBooster | 3 Backstory | 4 Wound | 5 JobFaceBonus |
| 6 JobBonus | 7 Cyberware | 8 TalentBoosterDebuff | 9 ArmorEffect | 10 TalentDebuff |
| 11 LoadedProgram | 12 MutationTempTrait | 13 MissionAdvantageBuff | 14 MissionAdvantageDebuff | 15 MutationTempTraitFace |

Cross-checked two ways: trait 2009's effect 10507 reads classification 12, which
this table calls `MutationTempTrait` and §2 documents as such; and
`EffectSpecialCode` decoded the same way gives `BlockMissions = 90`, matching
`_id_constants.csv`. Declaration order gives 12 = `MissionAdvantageBuff`.

**The 144 WoundRes-bearing effects:**

| Class | Rows | Range | |
|---|---|---|---|
| 1 TalentBuff | 9 | -50..+50 | limited-time |
| 3 Backstory | 40 | -50..+25 | always-active |
| 4 Wound | 4 | -20..-10 | limited-time |
| 7 Cyberware | 64 | -25..+25 | always-active |
| **9 ArmorEffect** | **22** | **+3..+30** | **always-active; excluded until 2026-09-10, counted since** |
| 10 TalentDebuff | 1 | -25..-25 | limited-time |
| 12 MutationTempTrait | 4 | -100..+50 | limited-time |

**Cyberware runs negative, and that is the mechanic: 51 of the 83 implants that
carry WoundRes are negative.** Measured across the reference save's roster, from
implants alone:

| | | | | |
|---|---|---|---|---|
| Pixel -39 | Jackknife -38 | Bracket -31 | Panther -30 | Bubbles -27 |
| Rhino -27 | Static -20 | Seraph -18 | Sentry -15 | Gyre -15 |
| Silent -15 | Tractor -11 | Sparklight -10 | | |

Against a 25% base this crew rolls 35-64% before armour. A maxed Triage Clinic is
+30 and pulls a 25% base to the floor.

**Armour counts since 2026-09-10** (David's ruling). This section used to say
"Gear is kept out so armour cannot buy the penalty back", per the 2026-08-30
ruling; that ruling is reversed. ArmorEffect rows run +3..+30, so armour now
offsets cyberware.

**The sources, and the readers:**

| Source | Reader | Note |
|---|---|---|
| Safehouse modules | `ReadGameSafehouses()` | Global, read once per mission |
| Traits | `ReadGameCharacterTraitsByCharacter(Int64)` | Already in hand from Phase B |
| Character effects | `ReadGameCharacterEffects(Int64)` | |
| Implants | `ReadGameCharacterImplants(Int64)` | The dominant term, and negative |
| Job nodes | `ReadGameCharacterJobNodes(Int64)` | **0 of 1,525 shipped nodes carry WoundRes** |
| Armour | `ReadGameArmorByCharacter(Int64)` | One row, not a list. Added 2026-09-10 |

**Armour, read.** `GameArmorModel` [measured, interop property tables] carries
`ArmorTypeId` and `GameEffectId`, and joins `ArmorData` (`ArmorModel`, with
`ArmorEffectId`), `EffectData` and `EffectDataCrafted` (both `EffectModel`).
Two effects per armour row are counted:

- the armour's own: `EffectData`, else `ArmorData.ArmorEffectId`, else
  `DataDb.ReadArmor(ArmorTypeId).ArmorEffectId`, then `ReadEffect`;
- the crafted upgrade: `EffectDataCrafted`, else `ReadEffect(GameEffectId)` when
  `GameEffectId` is non-zero. [fitted] `GameEffectId` is an `EffectModel` id:
  it exists on no other model, and `EffectDataCrafted` is the only
  `EffectModel` join beside it.

[unverified] What `ReadGameArmorByCharacter` returns for a merc with no armour.
Null and a row with `ArmorTypeId 0` both read as `armor 0`. A throw reads as
`armor UNREADABLE` with one warning, so if unarmoured mercs show that, the
reader throws on a miss (the by-id pattern in `docs/gotchas.md`) and the
warning can be ignored for them. That the returned row is the equipped armour
is also [unverified]; `IsEquipped` is not gated on because it is a UI-side
property that may not be filled on a database read.

Armour points go into the total and are reported as `gear +N` on the roll line,
not split into permanent/timed. An ArmorEffect arriving through another reader
counts the same way.

**Correction, 2026-09-10.** This section used to say: "All four per-character
models carry a joined `EffectData`, as `GameCharacterTraitModel` does, so no
`DataDb` hop and no id lookup is needed." The property exists on all four
(`CoreRPG_v1.dll` property tables), but only the trait reader was ever shown to
fill it (RUN44). The other three were assumed, and `AddRows` skipped a null
`EffectData` without logging anything.

**RUN63** [measured] is the first live run of this path. Turn 1248, PL 15, four
mercs (5 Stiletto, 22 Apex, 27 Sin, 30 Lance). Every roll line reads `[57 base,
no resist]`, there are no reader warnings, and the safehouse reads 0 on all three
paths. David reports those mercs carry Wound Resist sources. The log cannot show
which reader lost them: a reader that returned no rows, rows whose effects carry
no `WoundRes`, and rows with a null join all printed the same `no resist`.
[fitted] The join is null on the effect, implant and/or job-node readers. The
next run with the fix confirms or rules this out; see "Reading the roll line"
below.

**The fix.** A row without its joined `EffectData` has its effect read from
`DataDb` (`GameDb.dataDb`), cached per mission:

| Source | Effect id comes from | Then |
|---|---|---|
| trait | `TraitData.EffectTypeId`, else `ReadTrait(TraitTypeId)` | `ReadEffect(id)` |
| effect | the row's `EffectTypeId` | `ReadEffect(id)` |
| implant | `ImplantData.ImplantEffectId`, else `ReadImplant(ImplantTypeId)` | `ReadEffect(id)` |
| job | `NodeData.NodeEffect1Id`, else `ReadJobNode(JobNodeId)` | `ReadEffect(id)` |

A joined `EffectData` is still used first when present. Column names are
[measured] off the interop property tables. That `ReadImplant(long)` and
`ReadJobNode(long)` key on `ImplantTypeId` and `JobNodeId` is [unverified]; a
wrong key or a thrown reader shows as `UNRESOLVED` on the roll line.

**Reading the roll line.** Every roll line now ends with what each reader
returned:

```
[57 base - -27 resist (permanent -27); read trait 6, effect 0, implant 3 (2 with WoundRes, 3 via DataDb), job 14]
```

`via DataDb` counts rows whose join was null and whose effect was looked up;
`name no effect` counts looked-up rows whose content row points at effect 0
(normal for job nodes, which mostly grant talents); `UNRESOLVED` counts rows
whose join was null and whose lookup failed;
`UNREADABLE` means the reader threw or returned null; `PARTIAL` means it stopped
part way. The first lookup per reader also logs `returned rows with no joined
EffectData … Said once per reader`, which answers the join question directly.

All five readers thread one `seen` union, so an implant or armour effect
mirrored into the effect table counts once. (Until 2026-09-10 this paragraph
opened "Gear is excluded by dropping classification 9 wherever it appears";
that is no longer done.) The first such repeat is
logged, which is what tells a session whether a grant writes both a
`GameCharacterTrait` and a `GameCharacterEffect` row (§1).

The safehouse total is read **once per mission**, so a Triage Clinic built or
upgraded mid-session takes effect. It has three read paths — the dumped
`GameSafehouseModel` row reads `GetWoundRes 0` because its `Modules` dictionary
was not populated on that read path — so the mod prefers `GetWoundRes`, falls
back to `ModuleSummary.WoundRes`, then to summing `Modules[].ModuleData.WoundRes`,
and warns when the three disagree.

**Timed and always-active** separate on two axes, both used:
`EffectClassification` (talent effects, wounds and mutation temp traits are
limited-time; cyberware, backstory and armour always-active) and
`GameCharacterTraitModel.ExpiresTurn` (non-zero timed, zero permanent), the
game's own predicate, which overrides the classification for a trait row. Both
halves count toward the total; the split is logged, not configured.

## 10. Offline checks

`tests/fatigue/` holds checks against the built DLL — the rolls, the curve,
the clamp, the shipped config, the mitigation arithmetic, the resist aggregator,
and (Part 5, 2026-09-10) the solo exemption and the `DataDb` lookup. Part 3's
missions carry a second, already Off-Duty merc so they are not solo; that merc
writes nothing, and Parts 1-3 give the same results with and without the solo
change.

**State of the harness, 2026-09-10** [measured]: 14 checks fail and Part 4
crashes (`TargetParameterCountException` on `Load`) **before any of this day's
changes**. They assert the pre-retune shipped curve (PL 1 chance 10, now 15),
the flat keys removed 2026-09-07, and `Load(path)`'s old signature. They test
stale fixtures, not regressions. `Program.cs` now reports a Part 4 crash as one
failure instead of ending the run. Part 2 reads `/home/claude/work/ckf.hardmode.fatigue.json`,
which is the `fatigue` section of `mods/CKFHardMode/defaults/ckf.hardmode.json`
extracted on its own.
