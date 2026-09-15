// PowerLevelCap — recompute a mission's Power Level without the hard cap of 10.
//
//   MissionPowerLevel = round( (TeamPowerLevel + offset) * scalar )
//   clamped to [minCap, maxCap]
//
// WHERE TEAM POWER LEVEL ACTUALLY LIVES (Run22)
// ---------------------------------------------
// Run21 concluded the value belonged to the save and therefore to GameDb.
// Run22 tested that and it is wrong. GameDb's row has no such column:
//
//   GameDataModel numeric fields — Id=1  GameTurn=2040  Credits=1306
//                                  Heat=3  LastMissionTurn=0
//
// There is no PowerLevel on GameDataModel at all, which is why the priority
// list silently fell through to CoreDb every time and why every poll logged
// "AccessTools.Property: Could not find property ... PowerLevel" — roughly
// ninety percent of Run22's log was that one warning.
//
// CoreGameDataModel does carry it, and the profile holds one row per
// playthrough:
//
//   CoreGameDataModel — PowerLevel=6.62  Id=31  ActiveGame=1  DifficultyIndex=7
//
// The materializer fires for EVERY row, so Run22 absorbed a parade of other
// saves' values — 6.62, 5.565, 7.6925, 8.335, 8.53, 4.8625, 0.34, 3.37 ... —
// each one overwriting the last because they all share a rank. Only the row
// with ActiveGame = 1 was this playthrough, and a row filter was needed to
// say so.
//
// None of that machinery is here any more. It was deleted 2026-08-31 under
// docs/deprecation-plan.md §7.4: the readers, the row materializers, the
// setter hooks, the model priority ranking, the row filter and the poller,
// together with their five config keys — TeamPowerLevelSources,
// TeamRowSources, TeamModelPriority, TeamRowFilter and TeamPowerLevelProperty.
// The record above is kept because the wrong turn is the reusable part; the
// code is not.
//
// THE SOURCE, FOUND (Run23 + the Run14 member dump)
// -------------------------------------------------
// Run23 killed the database theory outright. With the row filter on, `team=`
// held still at 6.62 all session — and the game's own answers did not. Under
// identical settings, consecutive calls implied roughly 7, then roughly 8,
// then 7 again. A value that alternates between adjacent calls is not a stat
// being read from a row; no amount of picking a better row was going to
// reproduce it.
//
// The answer was sitting in Run14's member dump the whole time:
//
//   ===== RPG.Database.Models.GameDifficultyModel =====
//     FIELD  static IntPtr NativeFieldInfoPtr_teamPowerLevel
//     PROP   Single teamPowerLevel get/set
//
// GameDifficultyModel carries its own `teamPowerLevel`. It is on the instance
// the postfix is already handed as `__instance` — the same object we read
// BasePowerLevelOffset and PowerLevelScalar off. There was never anything to
// look up.
//
// So that property is the only source, and there is nothing left to fall
// through to. If the instance carries no readable property, or carries
// one that reads 0 — which a freshly constructed model does before the game
// fills it in — this file logs an error and leaves the game's own result
// alone. It never proceeds on a default: a default here is not a missing
// mission difficulty, it is a silently wrong one.
//
// The back-solve is the proof: `team=` and `implied team` should now agree on
// every unclamped line, including the Matrix ones that never fit 6.62.
//
// TWO KINDS OF CALL — DIFFICULTY AND REWARD (Run24, Run25)
// --------------------------------------------------------
// Run24 confirmed the instance read: `team=` tracked 6.62, 7.8 and 7.44 across
// save loads, and eleven of thirteen calculations matched round(team + offset)
// exactly. The two that did not both carried a non-zero arg0.
//
// Run25 identified arg0. It is not a mission level the game happens to be
// carrying around — it is the team's own standing, floored:
//
//     team 7.44 -> arg0 7        team 6.62 -> arg0 6        team 0.34 -> arg0 1
//
//     arg0 == max(1, Floor(teamPowerLevel))     7/7 calls, 3 different saves
//
// 6.62 is the case that settles it: Round would give 7, and the game passed 6.
//
// A method being handed Floor(TeamPowerLevel) and asked for a number is the
// shape of a REWARD calculation — payout tier, XP band, loot level — not a
// request for how hard to make a mission. Difficulty modifiers are not
// supposed to scale rewards; a hard mode that pays more for being hard is not
// a hard mode. Earlier versions of this file scaled those results anyway,
// which in Run25 turned a reward of 1 into 2 and one of 8 into 10.
//
// So a derived call always passes through: when arg0 > 0 the postfix returns
// immediately, before reading, scaling or clamping anything. The difficulty
// path — arg0 = 0, worked out from teamPowerLevel — is the only thing this file
// rewrites. That was DerivedCallMode; it is not configurable any more, because
// Recompute is the setting that turned a reward of 1 into 2.
//
// This is inference, not proof: the log shows the input, not the caller. What
// would settle it is instrumenting a reward site directly and watching whether
// its number tracks these returns.
//
// Matrix gets its own ceiling on the difficulty path. matrixMaxCap defaults to
// the stock 10, so hacking stays where the game put it while ground missions
// climb to maxCap.
//
// 3.0 moved these five keys out of the [PowerLevel] section of
// ckf.hardmode.cfg and into the "powerlevel" section of ckf.hardmode.json:
//
//   "powerlevel": {
//     "enabled": true,
//     "minCap": 1,
//     "maxCap": 20,
//     "matrixMaxCap": 10,        // 0 = use maxCap for Matrix too
//     "logFirst": 40
//   }
//
// That is the whole section. Seven keys were removed 2026-08-31 — DerivedCallMode,
// MatrixOffsetMode, TeamPowerLevelOverride, OffsetProperty, ScalarProperty,
// MatrixOffsetProperty and InstanceTeamProperty. Every one of them was a measured
// fact about the game's own model rather than a preference, and each is now a
// const at the top of the class with the run that pinned it named beside it.
//
// ONE INTERFACE FOR DIFFICULTY
// ----------------------------
// ScalarOverride, UseOffsetOverride and OffsetOverride are gone. They were
// duplicates: [Difficulty] PowerLevelScalar, BasePowerLevelOffset and
// MatrixPowerLevelOffset are the game's own settings under the game's own
// names, they are written onto this very model, and this file reads them off
// __instance. Two knobs for one value is a bug waiting to happen, and it had
// already produced one — the back-solve below subtracted the mod's offset from
// the game's answer, quietly reporting an implied Team Power Level that was
// off by the difference whenever OffsetOverride was set.
//
// So set difficulty in [Difficulty], or on the in-game sliders now that
// SliderRangeMultiplier gives them the range. This section keeps only what the
// sliders cannot express: the ceiling of 10 the game clamps its own result to.
//
// The Matrix offset REPLACING the base offset rather than adding to it is not a
// duplicate but a fact: it is this file's model of what the GAME does with
// MatrixPowerLevelOffset, Run21 confirmed it, and it is needed to reconstruct
// the game's own arithmetic. It is a const now for the same reason.

using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Reflection;
using System.Text.Json;
using System.Text.Json.Serialization;
using HarmonyLib;

namespace CKFHardMode
{
    internal static class PowerLevelCap
    {
        private const string DifficultyType = "RPG.Database.Models.GameDifficultyModel";
        private const string MethodName = "CalculatePowerLevel";

        private const BindingFlags Instance = BindingFlags.Public | BindingFlags.Instance;

        private static bool enabled;
        private static long minCap = 1, maxCap = 20, matrixMaxCap = 10;
        // Not configurable. David's ruling 2026-08-31: these are settled facts
        // about the game's own model, not knobs — each was pinned by a measured
        // run and there is no reason to type a different value.
        //
        //   PassThrough on a derived call — Run25 pinned arg0 to
        //     max(1, Floor(teamPowerLevel)) across three saves: the game handing
        //     its own standing back to itself, which is a reward calculation and
        //     not a request for a mission's difficulty.
        //   Matrix offset REPLACES the base offset rather than adding — Run21.
        //   The three property names are GameDifficultyModel's own columns.
        private const bool MatrixOffsetReplaces = true;
        private const string OffsetProp = "BasePowerLevelOffset";
        private const string ScalarProp = "PowerLevelScalar";
        private const string MatrixOffsetProp = "MatrixPowerLevelOffset";
        private const string InstanceTeamProp = "teamPowerLevel";
        private static bool warnedNoInstanceProp;
        private static bool warnedZeroInstance;
        private static bool loggedArg1Type;
        private static int logFirst = 40, logged;

        // Reflection cache. AccessTools.Property logs a warning on every miss,
        // and these lookups run once per calculation, so they go through plain
        // reflection and are resolved exactly once per type.
        private static readonly Dictionary<string, PropertyInfo> propCache =
            new Dictionary<string, PropertyInfo>(StringComparer.Ordinal);

        // 3.0: the five [PowerLevel] cfg keys are the "powerlevel" section of
        // ckf.hardmode.json. The section is new — it has no 2.x sidecar behind
        // it — and it is flat, so ConfigDoc.ReadSection does the grading and
        // the unknown-key report.
        private sealed class Options : ConfigDoc.IHasUnknownKeys
        {
            // RETIRED 2026-09-13. This used to be
            //     [JsonPropertyName("enabled")] public bool Enabled { get; set; } = true;
            // and Init branched on it. The gate is [Slices] PowerLevel in
            // ckf.hardmode.cfg now. Still parsed so an existing document is not
            // refused for a key that maps to no member; nothing branches on it.
            [JsonPropertyName("enabled")]      public bool? RetiredEnabled { get; set; }
            [JsonPropertyName("minCap")]       public int MinCap { get; set; } = 1;
            [JsonPropertyName("maxCap")]       public int MaxCap { get; set; } = 20;
            [JsonPropertyName("matrixMaxCap")] public int MatrixMaxCap { get; set; } = 10;
            [JsonPropertyName("logFirst")]     public int LogFirst { get; set; } = 40;
            [JsonExtensionData] public Dictionary<string, JsonElement> Unknown { get; set; }
            public Dictionary<string, JsonElement> UnknownKeys { get { return Unknown; } }
        }

        public static void Init(Harmony harmony)
        {
            if (!Slices.On("PowerLevel"))
            {
                Plugin.Log.LogInfo(Slices.OffBecause("PowerLevel",
                    "nothing is patched and the game's own clamp of 10 stands."));
                enabled = false;
                return;
            }

            var opt = ConfigDoc.ReadSection<Options>("PowerLevel", ConfigDoc.PowerLevel,
                "The mission Power Level ceiling is NOT lifted this launch — nothing is "
                + "patched and the game's own clamp of 10 stands.");
            if (opt == null) return;

            Slices.ReportRetiredGate("PowerLevel", ConfigDoc.PowerLevel,
                                     "PowerLevel", opt.RetiredEnabled);

            enabled = true;
            maxCap = opt.MaxCap;
            minCap = opt.MinCap;
            matrixMaxCap = opt.MatrixMaxCap;
            logFirst = opt.LogFirst;
            if (maxCap < minCap)
            {
                Plugin.Log.LogWarning($"PowerLevel: maxCap {maxCap} < minCap {minCap}. Not patching.");
                return;
            }
            // matrixMaxCap was never checked against minCap, and the clamp at
            // the bottom of After() is max(minCap, min(ceiling, rounded)) — so a
            // matrixMaxCap below minCap made minCap win and returned a Matrix
            // result ABOVE the very ceiling this key exists to impose, higher
            // than the game's own stock clamp, with nothing logged. Rather than
            // refuse the whole subsystem for one bad key, refuse the SEPARATE
            // MATRIX CEILING only: 0 is the file's existing spelling of "use
            // maxCap for Matrix too", and maxCap has just been checked against
            // minCap, so the clamp can no longer exceed the ceiling that applies.
            if (matrixMaxCap > 0 && matrixMaxCap < minCap)
            {
                Plugin.Log.LogWarning($"PowerLevel: matrixMaxCap {matrixMaxCap} < minCap {minCap}. "
                    + "minCap would win the clamp and push Matrix missions above matrixMaxCap, so "
                    + $"the separate Matrix ceiling is REFUSED — Matrix uses maxCap {maxCap} like "
                    + "everything else. Raise matrixMaxCap to at least minCap, or lower minCap.");
                matrixMaxCap = 0;
            }

            var type = AccessTools.TypeByName(DifficultyType);
            if (type == null) { Plugin.Log.LogError($"PowerLevel: no {DifficultyType}."); return; }
            var targets = AccessTools.GetDeclaredMethods(type)
                .Where(m => m.Name == MethodName && !m.IsAbstract).ToList();
            if (targets.Count == 0) { Plugin.Log.LogError($"PowerLevel: no {MethodName}."); return; }

            var postfix = new HarmonyMethod(AccessTools.Method(typeof(PowerLevelCap), nameof(After)));
            foreach (var m in targets)
            {
                try { harmony.Patch(m, postfix: postfix); }
                catch (Exception e) { Plugin.Log.LogError($"PowerLevel: patch failed: {e.Message}"); }
            }
        }

        // Matrix keeps its own ceiling so hacking can stay at the stock 10 while
        // ground missions climb. 0 means "no separate ceiling".
        private static long MatrixCeiling() =>
            matrixMaxCap > 0 ? Math.Min(maxCap, matrixMaxCap) : maxCap;
        // Cached, warning-free property lookup. AccessTools.Property logs on every
        // miss, and these run once per calculation.
        private static PropertyInfo PropOf(Type t, string name)
        {
            if (t == null || string.IsNullOrEmpty(name)) return null;
            var key = t.FullName + "|" + name;
            PropertyInfo p;
            if (propCache.TryGetValue(key, out p)) return p;
            for (var cur = t; cur != null && cur != typeof(object); cur = cur.BaseType)
            {
                try
                {
                    p = cur.GetProperty(name, Instance | BindingFlags.NonPublic
                                              | BindingFlags.DeclaredOnly);
                    if (p != null) break;
                }
                catch { }
            }
            propCache[key] = p;
            return p;
        }

        private static double? ReadOrNull(object instance, string prop)
        {
            if (instance == null || string.IsNullOrEmpty(prop)) return null;
            try
            {
                var p = PropOf(instance.GetType(), prop);
                if (p == null) return null;
                var v = p.GetValue(instance);
                if (v == null) return null;
                return Convert.ToDouble(v, CultureInfo.InvariantCulture);
            }
            catch { return null; }
        }

        private static double Read(object instance, string prop, double fallback)
            => ReadOrNull(instance, prop) ?? fallback;

        public static void After(object __instance, object[] __args, ref long __result)
        {
            if (!enabled) return;

            long arg0Value = 0;
            try
            {
                if (__args != null && __args.Length >= 1 && __args[0] != null)
                    arg0Value = Convert.ToInt64(__args[0], CultureInfo.InvariantCulture);
            }
            catch { }

            bool isMatrix = __args != null && __args.Length >= 2 && __args[1] is bool b && b;

            // Instrument, not a claim. Whether `__args[1] is bool` is how the
            // game marks a Matrix mission is not determinable from this source,
            // and the line above assumes it. Report what __args[1] actually was
            // on the first call so a play session can answer the question; the
            // discrimination itself is left exactly as it was.
            if (!loggedArg1Type)
            {
                loggedArg1Type = true;
                string a1 =
                    __args == null ? "__args was null"
                  : __args.Length < 2 ? $"absent (__args.Length={__args.Length})"
                  : __args[1] == null ? "null"
                  : __args[1].GetType().FullName + " = "
                        + Convert.ToString(__args[1], CultureInfo.InvariantCulture);
                Plugin.Log.LogInfo($"PowerLevel: first call — __args[1] was {a1}; this file read "
                    + $"it as isMatrix={isMatrix}. If that disagrees with the mission you were "
                    + "running, the Matrix discrimination is looking at the wrong argument.");
            }

            // arg0 > 0 is the game handing its own Team Power Level back to
            // itself — Run25 pinned it to max(1, Floor(teamPowerLevel)) exactly,
            // across three different saves. That is a reward calculation, not a
            // request for a mission's difficulty, and difficulty modifiers are
            // not meant to touch rewards. Bail out before we read, scale or
            // clamp anything.
            if (arg0Value > 0) return;   // a derived call always passes through

            // The value the game's own arithmetic uses lives on the instance we
            // were handed. It cannot be stale and cannot belong to another
            // playthrough, and since §7.4 it is the only source there is.
            double? live = ReadOrNull(__instance, InstanceTeamProp);

            // ONE path for "there is no readable value". This condition used to
            // be handled twice: a warning here that did not return, and a second
            // !HasValue block further down that returned but said only "Team
            // Power Level unknown". Both fired for the same call and the second
            // was reachable in no other case. Collapsed to this block; the
            // message below carries what both of them said.
            if (!live.HasValue)
            {
                if (!warnedNoInstanceProp)
                {
                    warnedNoInstanceProp = true;
                    Plugin.Log.LogWarning("PowerLevel: Team Power Level unknown — " +
                        $"GameDifficultyModel has no readable '{InstanceTeamProp}', so results " +
                        "are left exactly as the game computed them. The game has most likely " +
                        "renamed the column; point CKFDataDump's [Diagnostics] DumpMembers at " +
                        "GameDifficultyModel and compare.");
                }
                return;
            }

            // A freshly constructed model reads 0 before the game fills it in,
            // and Team Power Level is never legitimately 0. There is no database
            // fallback to divert to any more, so this cannot be papered over:
            // say so once and leave the game's own answer alone. Computing on
            // through would drive every mission to minCap, which is not a
            // missing number — it is a wrong one that looks like a real one.
            if (live.Value <= 0.0)
            {
                if (!warnedZeroInstance)
                {
                    warnedZeroInstance = true;
                    Plugin.Log.LogError($"PowerLevel: {InstanceTeamProp} read as 0 on " +
                        $"{__instance.GetType().Name} — Team Power Level is never legitimately " +
                        "0 and there is no fallback source, so Power Level is left exactly as " +
                        "the game computed it. The game has most likely renamed the column.");
                }
                return;
            }

            double team = live.Value;
            string teamSrc = InstanceTeamProp;

            // Every term now comes off the model. The [Difficulty] section writes
            // these same properties, so setting PowerLevelScalar there is what
            // steers this — there is no second copy of the knob to disagree with.
            double baseOff = Read(__instance, OffsetProp, 0.0);
            double mtxOff = Read(__instance, MatrixOffsetProp, 0.0);
            double scalar = Read(__instance, ScalarProp, 1.0);
            if (scalar == 0.0) scalar = 1.0;

            double offset = baseOff;
            if (isMatrix)
            {
                if (MatrixOffsetReplaces) offset = mtxOff;
            }

            double raw = (team + offset) * scalar;
            long rounded = (long)Math.Round(raw, MidpointRounding.AwayFromZero);
            long ceiling = isMatrix ? MatrixCeiling() : maxCap;
            long clamped = Math.Max(minCap, Math.Min(ceiling, rounded));

            if (logged < logFirst)
            {
                logged++;

                // Back-solve the game's own answer for the Team Power Level it
                // must have used. Every term comes off the model the game was
                // handed, so the scalar and offset we computed with ARE the
                // game's — there is no second copy of either left to disagree.
                double implied = (__result / scalar) - offset;
                bool maybeClamped = __result >= 10;   // the game's own ceiling

                Plugin.Log.LogInfo(
                    $"PowerLevel: team={team:0.##} ({teamSrc}) base={baseOff:0.##} " +
                    $"mtx={mtxOff:0.##} used={offset:0.##} scalar={scalar:0.##}" +
                    $"{(isMatrix ? " [matrix]" : "")} " +
                    $"-> raw={raw:0.##} round={rounded} clamp={clamped} (ceiling {ceiling})  " +
                    $"(game said {__result} for arg0={arg0Value}, implied team " +
                    $"{(maybeClamped ? ">=" : "~")}{implied:0.##} at game scalar {scalar:0.##}" +
                    $" offset {offset:0.##})" +
                    (maybeClamped || Math.Abs(implied - team) <= 0.5 ? "" : "   TEAM PL MISMATCH"));
            }

            __result = clamped;
        }
    }
}
