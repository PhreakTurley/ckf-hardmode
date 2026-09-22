# Writing Harmony patches for this game

Rules for adding Harmony patches to either plugin. Breaking them can make the
game stack-overflow during plugin loading, with a trace that points at someone
else's code. Prefer data changes (rules, overlays) to new patches wherever the
game already models the distinction you want.

Choose in this order:

1. Use a rule or overlay when a table already holds the value.
2. Call and sweep a pure arithmetic function when observation is enough.
3. Patch only a substantial method with a distinct job and body.

## Patch methods with unique work

> **Patch methods that do work. Never patch methods that only do arithmetic.**

An IL2CPP release build folds functions with identical machine code onto one
address, aggressively for small ones. Patch a folded address and you have
patched every method that shares it: the trampoline meant to reach the original
reaches the detour and recurses until the stack is gone.

- **Harmony reports success.** A `try`/`catch` around `harmony.Patch` catches a
  refused patch, not this.
- **The failure shows up in unrelated code.** One occurrence had
  `UnityEngine.GameObject.AddComponent`, called by a different plugin during its
  own load, entering the detour installed on
  `RulesUtil.CalculateMatrixLootAccountValue`.
- **Managed code cannot detect it in advance.** The `MethodInfo`s are distinct;
  only the code addresses coincide, and reflection cannot see code addresses.

Signs a target is unsafe:

- the body is plausibly one expression;
- the signature is nothing but primitives;
- sibling methods share the signature (`CalcluateMatrixLootFileValue(long,long)`
  and `CalculateMatrixLootAccountValue(long,long)`).

Safe targets are the opposite: factory or assembly methods with substantial,
unique bodies, such as `MissionFactory.ProcessMissionRequest` and
`GameDifficultyModel.ReconfigureDifficulty`.

Folding needs identical bodies. Hard Mode's `RewardCurve` patches
`RulesUtil.CalculateMissionPayment`, `CalculateMissionExperience` and
`CalculateMissionBonus` on that basis: each is a step table over different
constants, so no two can compile to the same code. That is a reasoned
exception, not a proof; see the header of `RewardCurve.cs`.

## Call pure functions instead of patching them

A pure function of one or two integers needs no interception. CKF Data Dump's
`CurveSweep.cs` calls the reward functions at load over power levels 0 to
`[Mission] CurveSweepMaxPowerLevel` (default 25), the two-argument valuers over
`CurveSweepBaseValues` × power level, and writes the whole table. Calling:

- cannot crash the game, since no detour exists;
- covers every level, including those above the PL 10 clamp that a session
  never produces;
- needs a launch, not a play session.

Whether a sweep sees `RewardCurve`'s patch depends on plugin load order, which
is not established [unverified]. Sweep with Hard Mode off for the stock curve;
`RewardCurve` logs the patched curve itself (`logEffectiveCurve`).

**Not for impure functions.** `MissionFactory.ProcGenerateHackOnlyPriceAndTurns`
draws random numbers, so calling it advances the RNG and changes which missions
the save offers. `CurveSweepIncludesProcGen` (default `false`) gates it. Its
return value is also unusable: every sweep point returned the same value,
`2185335553792` (`0x1fcd0263f00`), a heap pointer rather than a price
[measured]. Leave it off and recover hack pricing from `_mission_generated.csv`.

## Follow the interop safety checklist

- **Two interop proxies can resolve to one il2cpp method.** Reading the
  `NativeMethodInfoPtr_*` static field on the generated type catches that case,
  and `RewardCurve`, `MissionRewards`, `Fatigue`, `RowClone` and CKF Data Dump's
  `MissionProbe` / `TraitProbe` check it before patching. It does not catch
  folding: the field points at a `MethodInfo`, not at compiled code, and it
  reads zero until the method has been called once.
- **`const` fields cannot be patched.** IL2CPP inlines them. CKF Data Dump's
  `[Diagnostics] DumpMembers` reports whether a member is `const`, static or
  instance, and whether a property has a setter.
- **`__result` on a `void` method is refused** with an IL compile error. Use a
  prefix that takes the argument `ref`; the parameter name must match the game's.
- **Resolve each type name once and cache it.** `AccessTools.TypeByName` walks
  every loaded assembly, and `UnityEngine.CoreModule` throws
  `ReflectionTypeLoadException` on each walk, so HarmonyX logs about fourteen
  lines of noise per call.
- **Resolve members reflectively**, not against compile-time types, so a game
  update that renames something produces a warning instead of a crash.
- **Adjust the game's inputs and let it compute.** The `ReconfigureDifficulty`
  postfix writes onto the model the game reads; the `ProcessMissionRequest`
  prefix adjusts the request before the payout is computed. Fighting a clamp
  directly is harder and more fragile.

## Validate a new patch

- Resolve the target and parameters reflectively; a missing member must warn and
  leave the subsystem off rather than abort plugin loading.
- Check `NativeMethodInfoPtr_*` for duplicate proxy targets where applicable.
- Build the plugin, launch with the patch's slice enabled, and inspect the whole
  plugin-load section of `LogOutput.log`, including errors attributed to other
  plugins.
- Exercise the target path in game. A successful `harmony.Patch` call is not a
  runtime test.

Build and launch commands are owned by [`workflow.md`](workflow.md).

## Related

- [`gotchas.md`](gotchas.md)
- [`../mods/CKFHardMode/README.md`](../mods/CKFHardMode/README.md)
