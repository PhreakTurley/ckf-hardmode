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

## Weapon UI and localization

`StunClubPresentation.AfterRules` appends one `CommerceItemSpecialRule` to
`GameWeaponModel.CommerceItemSpecialRules` for content id 13000 while the
mechanic is active. It copies the list and preserves its existing entries,
including crit and stun rules. Other weapon ids and the disabled slice return
the original result. Failed text/list readback preserves the original result
and logs `StunClub UI: complete=false`.

The English templates live in `mods/CKFHardMode/Locales/en-US.json`, embedded
in the DLL by `CKFHardMode.csproj`; the placeholder uses the mechanic's
`ExtraPurePercent` constant. There is no extra installation file.

| Localization key | English template |
|---|---|
| `CKFHardMode.Weapon.KineticAsExtraPure.Title` | `+{0}% Kinetic as Extra Pure Damage` |
| `CKFHardMode.Weapon.KineticAsExtraPure.Description` | `Attacks with this weapon gain {0}% of Kinetic damage as extra Pure damage. Adds to other Kinetic as Extra Pure Damage bonuses.` |

For each club UI request, `LocalizedText` reads the current
`I18n.translationData` dictionary. It adds missing owned keys with the English
fallback, preserves existing translations, then formats the selected templates
with 50. Changing language uses the new active dictionary. No locale file,
save row or existing game localization key is rewritten.

[measured] The installed `CoreRPG_v1.dll` declares the getter returning
`Il2CppSystem.Collections.Generic.List<CommerceItemSpecialRule>`, its
`RuleTitle` and `RuleDescription` string properties, and the shared
`STEItemRulesListView.ShowSpecialRulesList` and `STEItemSpecialRuleView.Show`
UI declarations. It also declares `I18n.translationData`,
`Lib.SimpleJSON.JSONNode.AsObject`, the string indexer and `Value`,
`JSONClass.m_Dict`, and `JSONData(string)` used for runtime registration.
These declarations and a managed Harmony result replacement are checked by
the private harness. [unverified] Rendering the new entry in the actual
inventory/hover UI still needs the live check below.

## Evidence and remaining verification

- [measured] `sheets/raw/WeaponModel.csv`, row 289, identifies content row
  13000 as Stun Club, with `PhysicalDamage1=180`, `PureDamage1=80`,
  `BallisticDamage1=0`, all three mode-2 damage fields zero, and
  `WeaponEffect=80001`.
- [measured] The installed `BepInEx/interop/CoreRPG_v1.dll` declares
  `RulesUtil.CalculateAttackChance(ICombatEntity attacker,
  IWeaponDataProvider activeWeapon, ICombatEntity defender, AttackVector
  vector, Dictionary<long,RuleModel> rulesConfig,
  RPG.Core.Constants+CombatRuleHints ruleHint)`
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
- [measured] `Logs/StunClub-initialisation-refused-20261004.log`, row 577,
  reports that initialization refused and all StunClub hooks were inert.
  The installed assembly declares `CombatRuleHints` nested under
  `RPG.Core.Constants`. The offline harness reproduces the old lookup failure
  with the short name and resolves both calculation methods with the full
  nested name used by `StunClub.CalculationTargets`.
- [measured] `Logs/StunClub-live-20261004.log`, rows 549-551,
  records `WeaponModel[13000].PureDamage1` changing from 80 to zero, with
  the other pure/ballistic fields zero. Row 652 records a club hit with
  `PureDamageMelee 48 -> 98 -> 48`, contribution 50 and `complete=true`.
  This establishes additive stat input and restoration for the captured hit.
- [unverified] The native damage formula uses that input identically to
  Strength and other kinetic-as-extra-pure buffs. The scope trace does not
  establish the formula or how kinetic damage bonuses enter it.
- [unverified] An attack with another weapon while the club remains equipped
  receives no club bonus in a live game. The offline harness covers this
  exclusion; the captured live hit identifies the club.
- [measured] `Logs/StunClub-slashslide-retest-20261004.log`, rows 592-593,
  records two club hit calculations with `PureDamageMelee 12 -> 62 -> 12`,
  contribution 50 and `complete=true`. David identified this session as a
  Slashslide test; the trace itself does not record talent names. Both
  captured club hits received additive stat input and restored it.
- [unverified] Preempt reaches the patched hit calculation with the club
  identified as the weapon used. Talent attacks selecting the club while
  `ActiveWeapon` names another weapon also remain unverified: a chance call
  using the club must be checked against the corresponding hit call. The
  hooks do not infer a later hit's weapon from an earlier preview.

## Live UI check

Build using the [normal plugin build procedure](workflow.md#build-hard-mode).
Relaunch and inspect the low-level club in the inventory detail and hover
views. Its innate rules should include `+50% Kinetic as Extra Pure Damage`
and the description above, alongside its existing rules. Compare another
weapon and repeated openings; the entry should appear only on this club and
should not accumulate duplicates. Capture `BepInEx/LogOutput.log` before the
next launch. `StunClub UI: complete=true` establishes rule/text readback, not
rendering; confirm that the UI displays it as well.

The existing attack traces can be used for future damage troubleshooting:

The calculation log names the phase, content weapon id, stat before/during/
after, and club contribution. For club calls the stat should increase by 50
and return to its original value; other-weapon calls should contribute zero.
The hit calculation must identify the club for each club attack, even when
a talent selects it from another slot. The combat damage must follow the
game's ordinary percentage calculation, including its rounding and critical
behavior. A successful scope log alone does not establish that formula.

Sampling is synchronous entry/exit of `CalculateAttackChance` and
`ResolveDamageOnHit`, not a turn tick. Per launch, the first 40 chance
calculations and the first 40 hits have separate logging budgets, including
other weapons and enemy attacks. Preview traffic never consumes the hit
budget. Each phase emits an explicit `trace limit reached` notice after its
40th sample. Later calls are still changed and restored but are not sampled;
failure diagnostics remain enabled regardless of these limits. Restart for
a fresh capture if the relevant phase reaches its limit. No rows do not
establish that a talent bypassed these methods. Check the startup hook report,
limit notices and any `complete=false` errors before drawing a conclusion.

The private `tests/stunclub` harness exercises the real plugin code with
fake interop objects for identity, additive stat input, nested different
weapons, reversal and exception restoration. It also runs the production
calculation-method lookup against the installed interop assembly, including
the nested hint type, and checks failure diagnostics. Emitted log events are
checked after exhausting both sample budgets, including continued stat
restoration and failure reporting. It does not execute native game methods
or test damage semantics or talent coverage.
