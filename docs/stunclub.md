# Stun Club attack bonus

`StunClub.cs` implements an optional change for `(WeaponModel, 13000)` behind
`[Slices] StunClub`. Its schema default is `false`; the switch lives in
`BepInEx/config/ckf.hardmode.cfg`. Turn it off and relaunch/reload to reverse
both parts. The subsystem writes no save rows and creates no effects or traits.
It is independent of `ModelRules`.

## What the code changes

`StunClub.AfterWeaponRow` clears `PureDamage1`, `PureDamage2`,
`BallisticDamage1` and `BallisticDamage2` on that content row, after the
ordinary overlays. It preserves both kinetic columns and `WeaponEffect`.
Rows with other content ids, including enemy clones, are untouched.

`StunClub.Enter` adds 50 to the attacker's `ActiveEffect.PureDamageMelee`
while a native calculation runs. It does not calculate damage separately.
`AfterCalculation` restores the previous stat on success; `CalculationThrew`
also restores it on an exception and preserves the exception. Nested calls
for the same club reuse the contribution, and nested calls for another
weapon temporarily remove it. The contribution never remains on the entity
between calculations.

The attack-chance prefix selects the explicit `activeWeapon` argument.
The hit-resolution prefix selects `attacker.ActiveWeapon` because its
native method has no weapon parameter. Identity comes from
`GameWeaponModel.WeaponTypeId` or `WeaponModel.WeaponId`, after an interop
`TryCast`. The code does not interpret an inventory `Id` as a content id or
search equipped slots. A combined `GameWeaponDualModel` gets no contribution.
An unknown provider, unreadable aggregate or failed write disables further
edits for the launch and reports `complete=false`; restart with the switch
off to discard any already materialized base-damage edits.

## Evidence and remaining verification

- [measured] `sheets/raw/WeaponModel.csv`, row 289, identifies content row
  13000 as Stun Club, with `PhysicalDamage1=180`, `PureDamage1=80`,
  `BallisticDamage1=0`, all three mode-2 damage fields zero, and
  `WeaponEffect=80001`.
- [measured] The installed `BepInEx/interop/CoreRPG_v1.dll` declares
  `RulesUtil.CalculateAttackChance(ICombatEntity attacker,
  IWeaponDataProvider activeWeapon, ICombatEntity defender, AttackVector
  vector, Dictionary<long,RuleModel> rulesConfig, CombatRuleHints ruleHint)`
  returning `AttackChance`, and `RulesUtil.ResolveDamageOnHit(ICombatEntity
  attacker, ICombatEntity defender, AttackVector vector, AttackResult
  result)` returning `DamageResult`.
- [measured] The same metadata declares `ICombatEntity.ActiveEffect` and
  `ActiveWeapon`, `EffectModelBase.PureDamageMelee` with a writable `long`
  property, `GameWeaponModelBase.WeaponTypeId`, `WeaponModelBase.WeaponId`,
  the four writable per-mode damage properties, and
  `DataDb.GetRowWeaponModel` returning `WeaponModel`.
- [measured] `BepInEx/core/Il2CppInterop.Runtime.dll` declares
  `Il2CppObjectBase.Pointer` and the generic, zero-argument `TryCast<T>()`.
- [unverified] A temporary write to `ActiveEffect.PureDamageMelee` reaches
  the native damage calculation and stacks identically with Strength and
  other kinetic-as-extra-pure buffs. Metadata establishes declarations,
  not implementation or caller paths.
- [unverified] Slashslide and Preempt both reach the patched calculations
  with the club identified as the weapon used. In particular, a chance call
  using the club while `ActiveWeapon` still names another weapon must be
  checked against the corresponding hit call; the two hooks deliberately
  do not infer a later hit's weapon from an earlier preview.

## Live acceptance checks

Build using the [normal plugin build procedure](workflow.md#build-hard-mode).
With the switch on, enter a mission and capture `BepInEx/LogOutput.log` before
the next launch. Check normal club attacks, Slashslide and Preempt, then
attack with another weapon while the club remains equipped. Repeat the club
attacks with an existing kinetic-as-extra-pure buff to check additive
stacking. Compare with the switch off from the same pre-mod save.

The calculation log names the phase, content weapon id, stat before/during/
after, and club contribution. For club calls the stat should increase by 50
and return to its original value; other-weapon calls should contribute zero.
The hit calculation must identify the club for each club attack, even when
a talent selects it from another slot. The combat damage must follow the
game's ordinary percentage calculation, including its rounding and critical
behavior. A successful scope log alone does not establish that formula.

Sampling is synchronous entry/exit of `CalculateAttackChance` and
`ResolveDamageOnHit`, not a turn tick. The first 40 calculations per launch
are logged, including exclusions and previews; later calls are still changed
but are not logged. Restart for a fresh capture if previews exhaust the cap.
No rows do not establish that a talent bypassed these methods. Check the
startup hook report and the sample cap, and inspect any `complete=false`
errors before drawing a conclusion.

The private `tests/stunclub` harness exercises the real plugin code with
fake interop objects for identity, additive stat input, nested different
weapons, reversal and exception restoration. It does not test native damage
or talent coverage.
