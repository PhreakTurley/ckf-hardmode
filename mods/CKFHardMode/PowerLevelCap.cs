// PowerLevelCap — recompute a mission's Power Level without the hard cap of 10.
//
//   MissionPowerLevel = round( (TeamPowerLevel + offset) * scalar )
//   clamped to [minCap, maxCap]
//
// Mechanics and evidence: docs/power-level.md.
//
// THE SOURCE OF TEAM POWER LEVEL
// ------------------------------
// GameDifficultyModel carries its own `teamPowerLevel`:
//
//   ===== RPG.Database.Models.GameDifficultyModel =====
//     FIELD  static IntPtr NativeFieldInfoPtr_teamPowerLevel
//     PROP   Single teamPowerLevel get/set
//
// It is on the instance the postfix is already handed as `__instance`, the
// same object BasePowerLevelOffset and PowerLevelScalar are read off. It is the
// only source. Traps that rule out the alternatives [measured]:
//
//   - GameDataModel (GameDb) has no PowerLevel column at all.
//   - CoreGameDataModel (CoreDb) carries PowerLevel, but one row per
//     playthrough in the profile, and its materializer fires for EVERY row,
//     so a naive read takes other saves' values.
//   - Consecutive difficulty calls under identical settings imply different
//     team levels, which no stored stat can reproduce.
//
// If the instance carries no readable property, or carries one that reads 0
// (which a freshly constructed model does before the game fills it in), this
// file logs an error and leaves the game's own result alone. It never
// proceeds on a default: a default here is a silently wrong mission
// difficulty.
//
// The back-solve is the check: `team=` and `implied team` should agree on
// every unclamped line.
//
// TWO KINDS OF CALL — DIFFICULTY AND REWARD
// -----------------------------------------
// arg0 == 0 is the difficulty path, worked out from teamPowerLevel. arg0 > 0
// carries the team's own standing, floored [measured]:
//
//     arg0 == max(1, Floor(teamPowerLevel))
//
// A method handed Floor(TeamPowerLevel) and asked for a number looks like a
// REWARD calculation (payout tier, XP band, loot level), and a hard mode must
// not scale rewards. So a derived call always passes through: when arg0 > 0
// the postfix returns before reading, scaling or clamping anything. This is
// inference from the input, not the caller [unverified]; instrumenting a
// reward site directly would settle it.
//
// Matrix gets its own ceiling on the difficulty path. matrixMaxCap at 10 keeps
// hacking at the game's stock ceiling while ground missions climb to maxCap.
//
// SETTINGS: ckf.hardmode.d/powerlevel.json (the switch is [Slices] PowerLevel
// in ckf.hardmode.cfg). Keys: minCap, maxCap, matrixMaxCap (0 = use maxCap for
// Matrix too), logFirst. Defaults are in schema/powerlevel.schema.json.
//
// ONE INTERFACE FOR DIFFICULTY
// ----------------------------
// The game's own PowerLevelScalar, BasePowerLevelOffset and
// MatrixPowerLevelOffset are set on the in-game sliders (widened by
// difficulty.json) and read here off __instance. This file has no second copy
// of them: two knobs for one value would also make the back-solve report an
// implied Team Power Level off by the difference. It keeps only what the
// sliders cannot express, the ceiling of 10 the game clamps its result to.
//
// The facts about the game's model are consts, not settings (below).

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
        // Not configurable (David's rule): these are measured facts about the
        // game's own model, not knobs.
        //
        //   PassThrough on a derived call — see the header.
        //   Matrix offset REPLACES the base offset rather than adding
        //     [measured]; needed to reconstruct the game's own arithmetic.
        //   The property names are GameDifficultyModel's own columns.
        private const bool MatrixOffsetReplaces = true;
        private const string OffsetProp = "BasePowerLevelOffset";
        private const string ScalarProp = "PowerLevelScalar";
        private const string MatrixOffsetProp = "MatrixPowerLevelOffset";
        private const string InstanceTeamProp = "teamPowerLevel";
        private static bool warnedNoInstanceProp;
        private static bool warnedZeroInstance;
        private static bool loggedArg1Type;
        private static int logFirst, logged;

        // Reflection cache. AccessTools.Property logs a warning on every miss,
        // and these lookups run once per calculation, so they go through plain
        // reflection and are resolved exactly once per type.
        private static readonly Dictionary<string, PropertyInfo> propCache =
            new Dictionary<string, PropertyInfo>(StringComparer.Ordinal);

        // powerlevel.json. It is flat, so ConfigDoc.ReadSection does the
        // grading and the unknown-key report. Initialisers match the schema
        // defaults and apply only when a key is absent from the file.
        private sealed class Options : ConfigDoc.IHasUnknownKeys
        {
            // RETIRED gate. The switch is [Slices] PowerLevel in
            // ckf.hardmode.cfg. Still parsed so a file carrying it is not
            // refused for a key that maps to no member; nothing branches on it.
            [JsonPropertyName("enabled")]      public bool? RetiredEnabled { get; set; }
            [JsonPropertyName("minCap")]       public int MinCap { get; set; } = 1;
            [JsonPropertyName("maxCap")]       public int MaxCap { get; set; } = 20;
            [JsonPropertyName("matrixMaxCap")] public int MatrixMaxCap { get; set; } = 10;
            [JsonPropertyName("logFirst")]     public int LogFirst { get; set; }
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
            // The clamp at the bottom of After() is
            // max(minCap, min(ceiling, rounded)), so a matrixMaxCap below minCap
            // would make minCap win and return a Matrix result ABOVE the very
            // ceiling this key exists to impose. Rather than
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
            // itself: max(1, Floor(teamPowerLevel)) [measured; see the header].
            // That looks like a reward calculation, not a
            // request for a mission's difficulty, and difficulty modifiers are
            // not meant to touch rewards. Bail out before we read, scale or
            // clamp anything.
            if (arg0Value > 0) return;   // a derived call always passes through

            // The value the game's own arithmetic uses lives on the instance we
            // were handed. It cannot be stale and cannot belong to another
            // playthrough, and it is the only source there is.
            double? live = ReadOrNull(__instance, InstanceTeamProp);

            // ONE path for "there is no readable value", with one message.
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
            // and Team Power Level is never legitimately 0. There is no fallback
            // source, so this cannot be papered over:
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

            // Every term comes off the model. The in-game sliders write these
            // same properties, so there is no second copy of the knob to
            // disagree with.
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
