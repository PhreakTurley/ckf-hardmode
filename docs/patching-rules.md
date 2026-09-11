# Writing Harmony patches for this game

Rules for adding new C# to either plugin. Ignore them and the game
stack-overflows during plugin loading, with a trace that points at somebody
else's code.

## The rule

> **Patch methods that do work. Never patch methods that do arithmetic.**

In an IL2CPP release build the linker folds functions with identical machine
code onto a single address, aggressively for small ones. **Patch a folded
address and you have patched every method that shares it** — the trampoline that
should reach "the original" reaches the detour instead, and recurses until the
stack is gone.

Three things make this nasty:

1. **Harmony reports success.** A `try`/`catch` around `harmony.Patch` catches a
   *refused* patch, which is the benign failure. It does not catch this.
2. **The blast radius is unrelated code.** A real occurrence had
   `UnityEngine.GameObject.AddComponent` — called by a *different plugin* during
   its own load — entering the detour installed for
   `RulesUtil.CalculateMatrixLootAccountValue`. Nothing in our own logs pointed
   at us.
3. **It cannot be detected in advance from managed code.** The `MethodInfo`s are
   genuinely distinct; only the code addresses coincide, and managed reflection
   cannot see a code address.

## Signs you are about to patch something unsafe

- The body is plausibly one expression (`CalculateMissionPayment(long)`).
- The signature is nothing but primitives.
- There are sibling methods with an identical signature —
  `CalcluateMatrixLootFileValue(long,long)` and
  `CalculateMatrixLootAccountValue(long,long)` are the same shape, which is what
  makes them folding candidates.

Safe targets look the opposite: a factory or assembly method with a substantial,
unique body — `MissionFactory.ProcessMissionRequest`,
`GameDifficultyModel.ReconfigureDifficulty`,
`MissionFactory.BuildProcRequestFromDatabase`.

## What to do instead: call it

A pure function of one or two integers needs no interception.

```csharp
public static long CalculateMissionPayment(long powerLevel)
```

`CurveSweep.cs` invokes these at load and writes the whole table. The reward
functions sweep power level 0 to `[Mission] CurveSweepMaxPowerLevel` (default
25, but 10 in the shipped config); the two-argument valuers sweep
`CurveSweepBaseValues` against power level; the hack-only pricer sweeps its two
enum parameters instead. Calling is better on every axis:

- It cannot crash the game — no detour exists to loop.
- Coverage is complete. A postfix sees only the levels the game happened to
  roll; a sweep gets the whole range, including levels above the PL 10 clamp
  that a normal session never produces.
- It needs a launch rather than a play session.

**Exception: functions that are not pure.**
`MissionFactory.ProcGenerateHackOnlyPriceAndTurns` has "ProcGenerate" in the
name, and proc-gen routines here draw random numbers — calling it advances the
RNG and changes which missions the save offers. It stays off by default
(`CurveSweepIncludesProcGen`) — though check your own cfg, because the shipped
one has it on. A read-only mod does not get to quietly change the game.

**And calling it does not work anyway.** With the switch on, all 36 sweep points
returned the identical value `2185335553792` — `0x1fcd0263f00`, a heap pointer,
not a number. The method returns a struct or tuple that the sweep renders as a
long. So the switch costs RNG on a live save and yields nothing. Leave it off,
and recover hack pricing from `_mission_generated.csv` instead.

## Other things worth knowing

**Two interop proxies can resolve to the same il2cpp method.** That case *is*
detectable — read the `NativeMethodInfoPtr_*` static field on the generated
type. `CKFDataDump`'s **mission probe** checks this before each of its own
patches and refuses a collision loudly — the table dumper and tracer do not. It
does **not** catch the folding case above; nothing managed does.

**`const` fields cannot be patched at all.** IL2CPP inlines them at compile
time. `[Diagnostics] DumpMembers` reports whether a member is `const`, static or
instance, and whether a property has a setter — worth a run before designing
around a member.

**Prefer prefixes for `void` methods you want to influence.** Asking Harmony for
`__result` on a `void` method is refused outright with an IL compile error. A
prefix taking the argument `ref` works — that is how `Progression.cs` reaches
`SetMissionPowerLevel(float)`. The parameter name must match the game's for
Harmony to bind it.

**`AccessTools.TypeByName` is expensive here.** Each call walks every loaded
assembly calling `Assembly.GetTypes()`, and `UnityEngine.CoreModule` throws
`ReflectionTypeLoadException` every time, so HarmonyX logs fourteen lines of
noise per call. Ninety calls once made up most of a 4,900-line log and a visible
chunk of startup time. **Resolve each type name once and cache it.**

**Resolve members reflectively, not against compile-time types.** Both plugins
do this so they build without exact signatures and degrade gracefully — a game
update that renames something produces a warning rather than a crash.

**Let the game do its own arithmetic.** The pattern that works everywhere here
is to adjust the *inputs* the game will use and let it compute:
`ReconfigureDifficulty` postfix writes onto the model the game reads;
`ProcessMissionRequest` prefix adjusts the request before the payout is
computed. Fighting a clamp directly is both harder and more fragile.

**And prefer a rule to a hook** whenever the game has already modelled the
distinction you want. A `ckf.hardmode.rules.json` edit has no call-ordering
assumptions and needs no rebuild.
