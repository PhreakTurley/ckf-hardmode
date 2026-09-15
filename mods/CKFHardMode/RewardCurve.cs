// RewardCurve — overwrite the baseline reward tiers keyed on PowerLevelUnscaled.
//
// The game's reward baseline is a hardcoded step table, not a formula:
//
//     RulesUtil.CalculateMissionPayment(long unscaledPowerLevel)     -> credits
//     RulesUtil.CalculateMissionExperience(long unscaledPowerLevel)  -> XP per merc
//     RulesUtil.CalculateMissionBonus(long unscaledPowerLevel)       -> the unit
//                                                secondary objectives are denominated in
//
// It climbs to PL 10 and then goes flat: 2800 credits and 500 XP at PL 10 and
// the same at PL 25. Everything else in the economy is a multiplier on these
// three numbers — the contact term, the per-objective percentages, the mission
// type bonuses — so this is the one lever that moves the whole floor rather
// than tilting one part of it against another.
//
// It is also the only fix for the flatline. Lifting the Power Level cap sends
// the crew against PL 12-20 enemies while the reward side stays pinned at the
// PL 10 tier, because rewards key on PowerLevelUnscaled and the table has
// nothing above 10. Filling in rows 11-25 here is what closes that gap.
//
// WHY PATCHING THESE IS SAFE, AND WHERE THE LINE IS
// -------------------------------------------------
// docs/patching-rules.md says never to patch methods that do arithmetic,
// because an IL2CPP release build folds functions with identical machine code
// onto one address — patch the address and you have patched every method that
// shares it, and the trampoline recurses until the stack is gone. That is what
// killed CKFDataDump 1.1.0.
//
// Folding requires the bodies to be IDENTICAL. These three are step tables over
// different constants: 150/225/350/... against 100/120/145/... against
// 10/25/30/... No two of them can compile to the same code, and none of them
// can collide with the one-line `return a;` helpers that caused the crash.
//
// That is a reasoned argument, not a guarantee, so something is checked rather
// than assumed. Before patching, each proxy's Il2CppInterop
// NativeMethodInfoPtr_<name>_* static IntPtr field is read and the three values
// are compared; if any two coincide, nothing is patched and the reason is
// logged.
//
// Be exact about what that compares. The field holds a pointer to a MethodInfo
// — one per managed method — not the address of the compiled function. Whether
// two methods whose machine code the linker folded onto one address would then
// share a MethodInfo pointer is an OPEN QUESTION: it cannot be determined from
// this source. An earlier version of this header asserted it could ("a folded
// pair is exactly what that check catches"); that was a claim about the engine
// rather than a reading of this code, and it is withdrawn.
//
// The check is kept regardless, because two proxies resolving to one MethodInfo
// pointer is worth refusing to patch whatever the cause. Note also that the
// field is lazily initialised and reads zero until the method has been invoked
// at least once — which, at plugin load, it has not been. A zero is skipped, so
// in practice the comparison often cannot run at all. That case now logs a
// warning naming the method, so "checked, no folding" and "could not check" are
// told apart in the log instead of both looking clean.
//
//   "rewardcurve": { "enabled": true, "logEffectiveCurve": true,
//                    "curve": [ ... ] }
//
// 3.0 moved both switches out of the [RewardCurve] section of
// ckf.hardmode.cfg and into this one, beside the rows they gate.
//
// The table lives in the "rewardcurve" section of BepInEx/config/ckf.hardmode.json,
// one row per power level, shipped pre-filled with the game's own values so you can see the
// curve you are editing. Leave a field out, or set it below zero, to keep the
// game's number for that cell.
//
// VERIFYING IT TOOK
// -----------------
// NOT with _reward_curve.csv. CKF Data Dump loads first — 'ckf.datadump' sorts
// before 'ckf.hardmode' — and its sweep runs during that load, hundreds of log
// lines before this file patches anything. The sweep therefore always records
// the stock curve, patched or not. Measured: sweep at log line 4081, patch at
// 4548.
//
// So verify from this plugin instead. After patching, it calls the three
// functions itself over the table's range and logs what they now return. That
// is the real return value, read back through the patch rather than assumed
// from the file — for the cells it manages to read. A cell that could not be
// called prints "-", and the count of those is warned about under the table, so
// a run where nothing was readable does not look like a curve of dashes.

using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text.Json;
using System.Text.Json.Serialization;
using BepInEx;
using HarmonyLib;

namespace CKFHardMode
{
    internal static class RewardCurve
    {
        private const string TypeName = "RPG.Combat.RulesUtil";

        private static bool enabled, logEffective;

        private sealed class Tier
        {
            [JsonPropertyName("PowerLevel")] public int PowerLevel { get; set; }
            [JsonPropertyName("Payment")]    public double Payment { get; set; } = -1;
            [JsonPropertyName("Experience")] public double Experience { get; set; } = -1;
            [JsonPropertyName("Bonus")]      public double Bonus { get; set; } = -1;
        }

        private sealed class CurveFile
        {
            // RETIRED 2026-09-13. "enabled" used to be
            //     [JsonPropertyName("enabled")] public bool Enabled { get; set; } = true;
            // with the comment "3.0: both switches live here now. [RewardCurve]
            // Enabled and LogEffectiveCurve are gone from ckf.hardmode.cfg."
            // Half of that is reversed: the subsystem switch is back in
            // ckf.hardmode.cfg, as [Slices] RewardCurve (design.md section 3).
            // logEffectiveCurve is a setting rather than a gate and stays here.
            // "enabled" is still parsed so an existing document is not refused;
            // nothing branches on it.
            [JsonPropertyName("enabled")]           public bool? RetiredEnabled { get; set; }
            [JsonPropertyName("logEffectiveCurve")] public bool LogEffectiveCurve { get; set; } = true;
            [JsonPropertyName("curve")] public List<Tier> Curve { get; set; } = new List<Tier>();
        }

        // power level -> replacement, per function. Absent means "leave it".
        private static readonly Dictionary<long, long> Payment = new Dictionary<long, long>();
        private static readonly Dictionary<long, long> Experience = new Dictionary<long, long>();
        private static readonly Dictionary<long, long> Bonus = new Dictionary<long, long>();

        public static void Init(Harmony harmony)
        {
            // THE GATE IS READ FIRST, from ckf.hardmode.cfg. The section
            // carries the tiers and logEffectiveCurve now, not the switch.
            if (!Slices.On("RewardCurve"))
            {
                Plugin.Log.LogInfo(Slices.OffBecause("RewardCurve",
                    "nothing is patched and the game's own reward curve stands."));
                enabled = false;
                return;
            }

            // LoadTable still sets `logEffective`, and still leaves `enabled`
            // false when the section could not be read — which it says at Error
            // rather than letting this read like a toggle.
            LoadTable();
            if (!enabled) return;                        // LoadTable said why

            if (Payment.Count == 0 && Experience.Count == 0 && Bonus.Count == 0)
            {
                Plugin.Log.LogInfo("RewardCurve: no tier overrides set; nothing patched.");
                return;
            }

            var t = AccessTools.TypeByName(TypeName);
            if (t == null)
            {
                Plugin.Log.LogError($"RewardCurve: could not resolve {TypeName}.");
                return;
            }

            var targets = new[]
            {
                ("CalculateMissionPayment",    nameof(AfterPayment),    Payment.Count),
                ("CalculateMissionExperience", nameof(AfterExperience), Experience.Count),
                ("CalculateMissionBonus",      nameof(AfterBonus),      Bonus.Count),
            };

            // The folding check. Two proxies resolving to one MethodInfo pointer
            // are patched as one method under two names; patching both installs
            // two detours, which is how the trampoline starts chaining into
            // itself. What is compared is the NativeMethodInfoPtr_* field — see
            // the header on what that does and does not establish.
            var seen = new Dictionary<IntPtr, string>();
            var resolved = new List<(MethodInfo M, string Postfix)>();
            foreach (var (name, postfix, count) in targets)
            {
                if (count == 0) continue;

                var m = AccessTools.Method(t, name);
                if (m == null)
                {
                    Plugin.Log.LogWarning($"RewardCurve: {TypeName}.{name} not found; skipped.");
                    continue;
                }

                var ptr = NativePointer(m);
                if (ptr == IntPtr.Zero)
                {
                    // Zero is neither compared nor recorded, so this method is
                    // simply not checked — and it stays out of the set the other
                    // two are checked against. That used to happen silently,
                    // which made a check that ran and a check that could not run
                    // produce the same clean-looking load log. The field is
                    // lazily initialised and reads zero until the method has
                    // been invoked once, which at plugin load it has not been,
                    // so this is the expected case rather than a rare one.
                    Plugin.Log.LogWarning($"RewardCurve: the folding check could NOT be "
                        + $"performed for {name} — its NativeMethodInfoPtr_{name}_* field reads "
                        + "zero, which is what it holds until the method is first invoked. "
                        + "It is patched anyway; nothing was compared for it, so this load "
                        + "log says nothing either way about whether it shares a method with "
                        + "the others.");
                }
                else if (seen.TryGetValue(ptr, out var other))
                {
                    Plugin.Log.LogError($"RewardCurve: {name} and {other} resolve to the SAME "
                        + "native method — the linker folded them together. Patching either "
                        + "would patch both and recurse. Nothing has been patched. Use the "
                        + "per-mission-type levers in the \"missions\" section instead.");
                    return;
                }
                else seen[ptr] = name;

                resolved.Add((m, postfix));
            }

            foreach (var (m, postfix) in resolved)
            {
                try
                {
                    harmony.Patch(m, postfix: new HarmonyMethod(
                        AccessTools.Method(typeof(RewardCurve), postfix)));
                }
                catch (Exception e)
                {
                    Plugin.Log.LogError($"RewardCurve: could not patch {m.Name}: {e.Message}");
                }
            }

            LogEffectiveCurve(t);
        }

        // Read the curve back through the patch. This is the only honest check
        // available in-process: the other plugin's sweep runs too early to see
        // anything this file does.
        private static void LogEffectiveCurve(Type t)
        {
            if (!logEffective) return;
            try
            {
                var pay = AccessTools.Method(t, "CalculateMissionPayment");
                var xp  = AccessTools.Method(t, "CalculateMissionExperience");
                var bon = AccessTools.Method(t, "CalculateMissionBonus");

                var levels = Payment.Keys.Union(Experience.Keys).Union(Bonus.Keys)
                                    .OrderBy(x => x).ToList();
                if (levels.Count == 0) return;

                Plugin.Log.LogInfo("RewardCurve: effective curve, read back through the patch:");
                Plugin.Log.LogInfo("RewardCurve:   PL   payment       xp    bonus");

                // Every cell is read in its own try and prints "-" on failure.
                // That is kept — one unreadable cell should not lose the rest of
                // the table — but the failures are counted now: if the three
                // methods are not callable at plugin load, every column printed
                // "-" under a heading that calls this "the effective curve",
                // with nothing saying that nothing had been read.
                int unread = 0;
                foreach (var pl in levels)
                {
                    object a = null, b = null, c = null;
                    try { a = pay?.Invoke(null, new object[] { pl }); } catch { }
                    try { b = xp?.Invoke(null, new object[] { pl }); } catch { }
                    try { c = bon?.Invoke(null, new object[] { pl }); } catch { }
                    if (a == null) unread++;
                    if (b == null) unread++;
                    if (c == null) unread++;
                    Plugin.Log.LogInfo("RewardCurve:  "
                        + pl.ToString(CultureInfo.InvariantCulture).PadLeft(3)
                        + Member(a).PadLeft(10) + Member(b).PadLeft(9) + Member(c).PadLeft(9));
                }

                if (unread > 0)
                    Plugin.Log.LogWarning($"RewardCurve: {unread} of {levels.Count * 3} cell(s) "
                        + "could not be read back and printed '-', so the table above is "
                        + "INCOMPLETE and is not the effective curve its heading claims. Every "
                        + "cell failing usually means the three methods are not callable this "
                        + "early; it says nothing about whether the patches took.");
            }
            catch (Exception e)
            {
                Plugin.Log.LogWarning($"RewardCurve: could not read the curve back: {e.Message}");
            }
        }

        private static string Member(object v) =>
            v == null ? "-" : Convert.ToString(v, CultureInfo.InvariantCulture);

        private static IntPtr NativePointer(MethodInfo m)
        {
            try
            {
                var f = m.DeclaringType
                    .GetFields(BindingFlags.NonPublic | BindingFlags.Public | BindingFlags.Static)
                    .FirstOrDefault(x => x.FieldType == typeof(IntPtr)
                                      && x.Name.StartsWith("NativeMethodInfoPtr_" + m.Name + "_",
                                                           StringComparison.Ordinal));
                return f == null ? IntPtr.Zero : (IntPtr)f.GetValue(null);
            }
            catch { return IntPtr.Zero; }
        }

        // 3.0: the text comes from ConfigDoc. Only the source moved.
        private static void LoadTable()
        {
            var path = ConfigDoc.Where(ConfigDoc.RewardCurve);
            try
            {
                var text = ConfigDoc.SectionText(ConfigDoc.RewardCurve);
                if (text == null)
                {
                    // AGENTS.md §3: an absent section and an unreadable document
                    // are different findings and do not share a log level.
                    var why = $"RewardCurve: {ConfigDoc.WhyNo(ConfigDoc.RewardCurve)}. Since 3.0 "
                        + "that section carries the subsystem switch as well as the tiers, so "
                        + "nothing is applied and nothing is patched.";
                    if (ConfigDoc.CouldNotRead(ConfigDoc.RewardCurve))
                        Plugin.Log.LogError(why);
                    else Plugin.Log.LogWarning(why);
                    return;
                }

                var opts = new JsonSerializerOptions
                {
                    ReadCommentHandling = JsonCommentHandling.Skip,
                    AllowTrailingCommas = true
                };
                var file = JsonSerializer.Deserialize<CurveFile>(text, opts);

                if (file != null)
                    Slices.ReportRetiredGate("RewardCurve", ConfigDoc.RewardCurve,
                                             "RewardCurve", file.RetiredEnabled);
                logEffective = file == null || file.LogEffectiveCurve;
                enabled = true;

                foreach (var tier in file?.Curve ?? new List<Tier>())
                {
                    long pl = tier.PowerLevel;
                    if (tier.Payment    >= 0) Payment[pl]    = (long)Math.Round(tier.Payment);
                    if (tier.Experience >= 0) Experience[pl] = (long)Math.Round(tier.Experience);
                    if (tier.Bonus      >= 0) Bonus[pl]      = (long)Math.Round(tier.Bonus);
                }

                Plugin.Log.LogInfo($"RewardCurve: read {file?.Curve?.Count ?? 0} tier row(s) "
                                 + $"from {path}.");
            }
            catch (Exception e)
            {
                enabled = false;
                Plugin.Log.LogError($"RewardCurve: failed to read {path}: {e.Message}. "
                    + "No tiers are overridden and nothing is patched.");
            }
        }

        // static long CalculateMissionPayment(long powerLevel), and siblings.
        // __args rather than a named parameter: the argument name is the game's
        // and differs between the three.
        public static void AfterPayment(object[] __args, ref long __result)
            => Apply(Payment, __args, ref __result);

        public static void AfterExperience(object[] __args, ref long __result)
            => Apply(Experience, __args, ref __result);

        public static void AfterBonus(object[] __args, ref long __result)
            => Apply(Bonus, __args, ref __result);

        private static void Apply(Dictionary<long, long> table,
                                  object[] args, ref long result)
        {
            if (!enabled || table.Count == 0) return;
            if (args == null || args.Length == 0 || args[0] == null) return;

            long pl;
            try { pl = Convert.ToInt64(args[0], CultureInfo.InvariantCulture); }
            catch { return; }

            long replacement;
            if (!table.TryGetValue(pl, out replacement)) return;
            if (replacement == result) return;

            result = replacement;
        }
    }
}
