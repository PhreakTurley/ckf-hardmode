// MissionRewards — per-mission-type control of payment, XP and Team Power Level.
//
// One job: the game hardcodes a mission's payment, XP and power-level bonus in
// a factory method with no table behind them. This exposes those three fields
// per MissionTypeId and lets you overwrite them.
//
// TEAM POWER LEVEL IS NOT DONE HERE — SEE THE RULES FILE
// -----------------------------------------------------
// An earlier version of this file scaled the Team Power Level a solo-hack
// mission awards, by bracketing the victory screen's power-level step to
// attribute an otherwise context-free call on GameDifficultyModel. That is all
// gone, because the game already separates these missions itself.
//
// MissionPowerLevelModel holds 63 rows: three ActionClass bands x 21 relative
// power levels, and the bands are exactly x2 apart on every row —
//
//     ActionClass 1 = story missions      full rate
//     ActionClass 2 = proc-gen missions   half
//     ActionClass 3 = solo hack missions  quarter
//
// (story-driven solo hacks score as class 1, which is intended). So changing
// what a hack job awards is a data edit against class 3 in
// ckf.hardmode.rules.json, with no patch, no call-ordering assumption and
// nothing to verify at runtime:
//
//     { "model": "MissionPowerLevelModel", "where": { "ActionClass": 3 },
//       "multiply": { "PowerLevelFraction": 0.5 } }
//
// A rule beats a hook whenever the game has already modelled the distinction
// you want. It had.
//
// HOW IT INTERVENES
// -----------------
// Through MissionFactory.ProcessMissionRequest, which every mission passes
// through, as a PREFIX on the MissionRequestModel rather than a postfix on the
// finished GameMissionModel. Editing the request means the game does its own
// arithmetic on values we supplied and everything downstream stays consistent —
// the same reason CKFHardMode reconfigures difficulty rather than fighting the
// clamps. See docs/mission-rewards.md.
//
// The fields are BonusPayment and BonusExperience, which are PERCENTAGES applied
// to the base curve, and PowerLevelBonus. Observed shipped values: a contact
// mission at +50 / +110, a safehouse raid at -100 / -75.
//
// ONE LEVER PER MISSION TYPE
// --------------------------
// Entries in the "missions" section of BepInEx/config/ckf.hardmode.json,
// keyed by exact MissionTypeId. There is no pattern-bucket layer any more: the
// PureCombatTypes / SoloHackTypes lists and their five bonus knobs were a
// second way to set the same three fields, and they had already drifted —
// the shipped cfg's PureCombatTypes had lost KillBoss and Kill3 relative to
// the source default, so the live install classified those missions
// differently from what the source said. See docs/deprecation-plan.md §7.2.
//
// The reward stack is now two layers with no overlap:
// the "rewardcurve" section of ckf.hardmode.json sets the base per power
// level, and the "missions" section adjusts one mission type.
//
//   "missions": { "enabled": true, "missions": [ ... ] }
//
// 3.0 moved the switch out of [MissionRewards] Enabled in ckf.hardmode.cfg and
// into this section, beside the rows it gates. (This header used to say the
// default was false. It is true; the schema is authoritative.)
//
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
    internal static class MissionRewards
    {
        private static bool enabled;

        // Exact MissionTypeId -> its own overrides, from
        // the "missions" section of BepInEx/config/ckf.hardmode.json. The only
        // per-mission lever.
        private static readonly Dictionary<string, MissionOverride> ByType =
            new Dictionary<string, MissionOverride>(StringComparer.OrdinalIgnoreCase);

        public static void Init(Harmony harmony)
        {
            // THE GATE IS READ FIRST, from ckf.hardmode.cfg. The "missions"
            // section carries only the per-type overrides now.
            //
            // CORRECTION, 2026-09-13. This comment used to read "The section is
            // read first now: it carries the switch as well as the overrides."
            // The switch is back in ckf.hardmode.cfg as [Slices] MissionRewards
            // (design.md section 3), and this gate is what reads it.
            //
            // This gate was MISSING for one revision on 2026-09-13: the
            // "enabled" branch was deleted out of LoadOverrides and nothing was
            // put here in its place, so this subsystem had no gate at all and
            // ran unconditionally. Caught by comparing Plugin.Binds.g.cs's 42
            // [Slices] keys against the keys the plugin actually reads --
            // MissionRewards was the one declared key that neither the overlay
            // file table nor any Slices.On call named.
            if (!Slices.On("MissionRewards"))
            {
                Plugin.Log.LogInfo(Slices.OffBecause("MissionRewards",
                    "no hook is installed and no per-mission override is applied."));
                enabled = false;
                return;
            }

            // LoadOverrides still leaves `enabled` false when the section could
            // not be read at all — which it says at Error rather than letting
            // this read like someone turned it off.
            LoadOverrides();

            if (!enabled) return;                    // LoadOverrides said why

            int n = 0;
            n += Patch(harmony, "RPG.Database.MissionFactory", "ProcessMissionRequest",
                       nameof(BeforeProcessMissionRequest), null);
            n += Patch(harmony, "RPG.Database.MissionFactory", "ProcessMissionRequest",
                       null, nameof(AfterProcessMissionRequest));

            // Only hook the reward materializer if something actually asks for
            // it. It is on the game's hot path for every reward row read.
            if (ByType.Values.Any(o => (o.Obj != null && o.Obj.Kind != AdjustKind.None)
                                    || (o.Sec != null && o.Sec.Kind != AdjustKind.None)))
                n += Patch(harmony, "RPG.Database.GameDb", "GetRowGameMissionRewardModel",
                           null, nameof(AfterGetRowMissionReward));

            // n was accumulated and never read: a MissionFactory that could not
            // be resolved produced a per-call LogWarning and no summary, so the
            // log said "could not resolve" once and then looked normal.
            // ModelRules and Plugin both check their patch counts; this does now.
            if (n == 0)
                Plugin.Log.LogError("MissionRewards: NOTHING HOOKED — not one patch took, on "
                    + "RPG.Database.MissionFactory.ProcessMissionRequest or on "
                    + "RPG.Database.GameDb.GetRowGameMissionRewardModel, so no per-type override "
                    + "can fire and the \"missions\" section of ckf.hardmode.json has no effect "
                    + "this session. The warnings above name what could not be resolved.");

            // The two caches this file keeps — MissionType and OriginalQuantity
            // — are keyed by ids that belong to ONE save: a MissionId, and a
            // GameMissionRewardModel row id. Both have to be dropped when a
            // different save is loaded. Same seam Elapse and Fatigue patch, for
            // the same reason.
            int loadHooks = PatchLoadHooks(harmony);
            if (loadHooks == 0)
                Plugin.Log.LogWarning($"MissionRewards: could not patch {GameManagementTypeName}"
                    + ".LoadGame/LoadGameSlot, so the mission-type map and the original-quantity "
                    + "snapshots are never cleared. What that costs: play save A and then save B "
                    + "in one process and B's reward rows reuse A's row ids, so B's reward is "
                    + "scaled off the base value remembered for A's row, and a MissionId the two "
                    + "saves share makes B's mission take A's mission type and so A's multiplier. "
                    + "Both maps also grow for the life of the process. Restart the game between "
                    + "saves. Worth reporting.");
        }

        // ViewModel_GameManagement.LoadGame / .LoadGameSlot — the only two
        // methods in the interop assembly that name loading a saved game.
        // Whether either fires on the path the player takes is not determinable
        // from this source; the warning above is what a play session answers it
        // with. Elapse and Fatigue patch the same pair.
        private const string GameManagementTypeName = "ViewModel_GameManagement";

        // LoadGame and LoadGameSlot, postfixed, in ONE pass over the type.
        //
        // This does not go through the general Patch helper above, and the
        // reason is the reason Elapse has AlreadyClaimed: two interop proxies
        // that resolve to one il2cpp method would take two detours on one
        // address. Catching that means comparing the two NAMES against each
        // other, and Patch is called once per name, so its bookkeeping could
        // never span the pair. Progression.PatchLoadHooks is the same code for
        // the same reason.
        //
        // [measured] Both names really do fire, separately, on one load:
        // Log17/Log18 line 4240-4241 and Run56 line 4417-4420 each show the
        // Elapse and Fatigue load lines TWICE per load. So the pair is not
        // folded on this build, and ForgetSession runs twice per load. That is
        // idempotent — the second pass clears maps the first already emptied —
        // but it does mean two log lines per load, which is expected, not a
        // double-fire.
        private static int PatchLoadHooks(Harmony harmony)
        {
            var t = AccessTools.TypeByName(GameManagementTypeName);
            if (t == null)
            {
                Plugin.Log.LogWarning($"MissionRewards: could not resolve "
                                    + $"{GameManagementTypeName}.");
                return 0;
            }

            var pf = new HarmonyMethod(AccessTools.Method(typeof(MissionRewards),
                                                          nameof(AfterLoadGame)));
            var claimed = new Dictionary<IntPtr, string>();
            int ok = 0;
            foreach (var m in AccessTools.GetDeclaredMethods(t))
            {
                if (m.IsAbstract) continue;
                if (m.Name != "LoadGame" && m.Name != "LoadGameSlot") continue;

                var ptr = NativePointer(m);
                string owner;
                if (ptr != IntPtr.Zero && claimed.TryGetValue(ptr, out owner))
                {
                    Plugin.Log.LogWarning($"MissionRewards: NOT patching {t.Name}.{m.Name} — it "
                        + $"is the same il2cpp method as {owner}.");
                    continue;
                }

                try
                {
                    harmony.Patch(m, postfix: pf);
                    if (ptr != IntPtr.Zero) claimed[ptr] = m.Name;
                    ok++;
                }
                catch (Exception e)
                {
                    Plugin.Log.LogWarning($"MissionRewards: could not patch {t.Name}.{m.Name}: "
                                        + e.Message);
                }
            }
            return ok;
        }

        // The il2cpp MethodInfo* an interop proxy caches, or Zero when the
        // field is absent or has not been initialised yet. Same helper as
        // Progression.NativePointer. A Zero reads as "cannot compare", so the
        // dedup above simply does not fire for that method rather than
        // guessing.
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

        // Postfix on that pair. Takes no arguments on purpose: it wants the fact
        // that a load happened, nothing out of it, and a signature that cannot
        // go stale when the model types move.
        public static void AfterLoadGame()
        {
            if (!enabled) return;
            try { ForgetSession("a save was loaded"); }
            catch (Exception e)
            {
                Plugin.Log.LogError($"MissionRewards: the load hook threw and was swallowed: {e}");
            }
        }

        // Everything keyed by a save-local id. missionsLogged is deliberately
        // NOT reset: it is a log budget rather than state, and clearing it would
        // reprint the whole mission report after every load.
        private static void ForgetSession(string why)
        {
            int types = MissionType.Count, rows = OriginalQuantity.Count;
            MissionType.Clear();
            OriginalQuantity.Clear();
            Plugin.Log.LogInfo($"MissionRewards: {why} — dropped {types} mission-type "
                + $"mapping(s) and {rows} original-quantity snapshot(s). Both are keyed by ids "
                + "that belong to the save that was open, so keeping them would price the new "
                + "save's rewards off the old save's numbers.");
        }

        // ---- the intervention ------------------------------------------------

        // ProcessMissionRequest(DataLayer, GameDataModel, MissionRequestModel,
        //                       GameDifficultyModel, Single)
        public static void BeforeProcessMissionRequest(object[] __args)
        {
            if (!enabled) return;
            try
            {
                var req = __args != null && __args.Length > 2 ? __args[2] : null;
                if (req == null) return;

                var typeId = Str(Get(req, "MissionTypeId"));

                // An exact entry in the missions file wins outright. It is the
                // more specific statement of intent, and it is the only way to
                // give one type a different number from its family.
                //
                // Tested for EMPTY, not null: Str returns "" for a missing
                // member and never null, so the old `typeId == null` guard could
                // not fire and a request carrying no MissionTypeId went on to
                // look itself up under "".
                MissionOverride ov;
                if (typeId.Length == 0
                 || !ByType.TryGetValue(typeId, out ov) || !ov.Active) return;

                ApplyField(req, "BonusPayment", ov.Pay, typeId);
                ApplyField(req, "BonusExperience", ov.Exp, typeId);
                ApplyField(req, "PowerLevelBonus", ov.Pl, typeId);
            }
            catch (Exception e) { Once("prefix", e); }
        }

        private static void ApplyField(object req, string field, Adjust adj, string typeId)
        {
            if (adj == null || adj.Kind == AdjustKind.None) return;

            var current = Get(req, field);
            if (current == null) return;

            // Carried as double, not long. Forcing every field through Int64
            // first truncated fractional targets: "x1.5" on a PowerLevelBonus
            // holding 1 stored 2, "x0.4" stored 0 and deleted the bonus
            // outright, "=1.5" stored 2, and a float column already holding 0.5
            // read back as 0 — Convert.ToInt64 rounds halves to even — so any
            // later multiply produced 0. Rounding now happens once, in Set, and
            // only when the destination column is integral.
            double before;
            try { before = Convert.ToDouble(current, CultureInfo.InvariantCulture); }
            catch { return; }

            double after = adj.Apply(before, Integral(req, field));
            if (after == before) return;

            Set(req, field, after);
        }

        // True when the destination column stores whole numbers, which is what
        // decides whether a fractional adjustment survives. The Accessor built
        // for this column already resolved the property and peeled Nullable<>
        // off its type, so ask it rather than working that out again here; the
        // fallback covers the fields, which Accessor does not model and which
        // these request models mix in with the properties.
        private static bool Integral(object target, string name)
        {
            Type u = null;

            var acc = Accessors.Get(target.GetType(), name);
            if (acc != null && acc.Exists) u = acc.Underlying;

            if (u == null)
            {
                var mi = Find(target, name);
                var p = mi as PropertyInfo;
                var f = mi as FieldInfo;
                var t = p != null ? p.PropertyType : f != null ? f.FieldType : null;
                // Unknown column: keep the whole-number behaviour this file had
                // before, so an unresolvable field cannot start storing halves.
                if (t == null) return true;
                u = Nullable.GetUnderlyingType(t) ?? t;
            }

            switch (Type.GetTypeCode(u))
            {
                case TypeCode.Single:
                case TypeCode.Double:
                case TypeCode.Decimal:
                    return false;
                default:
                    return true;
            }
        }

        // The "expose" half. Every mission is reported with the fields that
        // carry its reward, matched or not, so a type the missions file misses
        // is a visible line rather than silence. This method used to contain no
        // logging at all — the comment promised a report that was never written.
        //
        // Bounded by a plain const counter: there is no [MissionRewards]
        // LogFirst key and the bind table is generated from the schema, so the
        // budget lives here rather than in config.
        private const int LogFirstMissions = 40;
        private static int missionsLogged;

        public static void AfterProcessMissionRequest(object[] __args, object __result)
        {
            if (!enabled || __result == null) return;
            try
            {
                var typeId = Str(Get(__result, "MissionTypeId"));

                // Remember which mission is which type. The per-objective reward
                // rows arrive later and carry only a MissionId, so without this
                // map there is no way to know whose objective a row belongs to.
                //
                // Empty, not null: Str returns "" for a missing member and never
                // null, so the old `typeId != null` guard was always true and a
                // mission carrying no MissionTypeId was filed under "". Such a
                // row is rejected now — a key nothing can match is worse than no
                // key, because it silently claims the row was understood.
                var mid = Get(__result, "Id");
                if (mid != null && typeId.Length != 0)
                {
                    try { MissionType[Convert.ToInt64(mid, CultureInfo.InvariantCulture)] = typeId; }
                    catch { }
                }

                if (missionsLogged < LogFirstMissions)
                {
                    missionsLogged++;

                    MissionOverride ov;
                    bool matched = typeId.Length != 0
                                && ByType.TryGetValue(typeId, out ov) && ov.Active;

                    Plugin.Log.LogInfo("MissionRewards: mission "
                        + (typeId.Length == 0 ? "<no MissionTypeId>" : typeId)
                        + " pay=" + Fld(__result, "BonusPayment")
                        + " xp=" + Fld(__result, "BonusExperience")
                        + " pl=" + Fld(__result, "PowerLevelBonus") + " — "
                        + (matched ? "an override in the \"missions\" section applies."
                                   : "no entry in the \"missions\" section; left alone.")
                        + (missionsLogged == LogFirstMissions
                            ? $" ({LogFirstMissions} mission(s) reported — quiet from here.)"
                            : ""));
                }
            }
            catch (Exception e) { Once("postfix", e); }
        }

        // A field's value for the report, or "-" when the model carries no such
        // member. Str alone cannot tell those apart: it returns "" for both.
        private static string Fld(object row, string name)
        {
            var v = Get(row, name);
            return v == null ? "-" : Str(v);
        }

        // ---- per-objective payments -----------------------------------------

        private static readonly Dictionary<long, string> MissionType =
            new Dictionary<long, string>();

        // RewardQuantity is a GameDb column: the row comes from the save, so a
        // multiply applied twice compounds. Remember the first value seen for a
        // row and always scale THAT, which makes the edit idempotent no matter
        // how many times the game re-reads it.
        private static readonly Dictionary<long, double> OriginalQuantity =
            new Dictionary<long, double>();

        // RewardTypes that pay credits. A mission's reward rows are a mix: the
        // cash terms that are part of what the job is worth, and secondary
        // objectives handing out blueprints, Influence, XP and cubes. Scaling
        // RewardQuantity on a Blueprint row would multiply the number of
        // blueprints, which is not what an ObjectivePayment multiplier means.
        private const long RewardTypePayment = 7;
        private const long RewardTypePaymentStatic = 13;

        // ModelRules postfixes this same GameDb.GetRowGameMissionRewardModel
        // whenever a rule names that model, from a DIFFERENT Harmony instance
        // ('ckf.hardmode' vs 'ckf.hardmode.missionrewards'), and both write
        // RewardQuantity. With no priority declared anywhere in the assembly the
        // order was whatever Harmony happened to pick, and OriginalQuantity
        // cached whichever value it saw FIRST for the rest of the session —
        // stable, and half the time wrong.
        //
        // Chosen order: this postfix runs FIRST. Harmony runs higher-priority
        // postfixes earlier, so Priority.First puts this ahead of ModelRules and
        // the snapshot below is the game's own stock RewardQuantity — the only
        // value that is the same every session, and the one the comment on
        // OriginalQuantity has always claimed it holds. ModelRules' multiply
        // then applies on top of ours.
        //
        // ModelRules.AfterGetRow needs [HarmonyPriority(Priority.Last)] for the
        // pair to be consistent; that file is not edited here.
        [HarmonyPriority(Priority.First)]
        public static void AfterGetRowMissionReward(object __result)
        {
            if (!enabled || __result == null) return;
            try
            {
                var rtRaw = Get(__result, "RewardTypeId");
                if (rtRaw == null) return;
                long rt = Convert.ToInt64(rtRaw, CultureInfo.InvariantCulture);
                if (rt != RewardTypePayment && rt != RewardTypePaymentStatic) return;

                var midRaw = Get(__result, "MissionId");
                if (midRaw == null) return;
                long mid = Convert.ToInt64(midRaw, CultureInfo.InvariantCulture);

                string typeId;
                if (!MissionType.TryGetValue(mid, out typeId)) return;

                MissionOverride ov;
                if (!ByType.TryGetValue(typeId, out ov)) return;

                // Two kinds of cash reward share RewardTypeId 7, and they are
                // not the same thing. A row with no goal, no turn limit and no
                // alarm ceiling is one of the mission's own terms — 30% per file
                // looted, per captain killed. A row carrying any of those is a
                // randomly generated secondary objective paying a bonus.
                //
                // Scaling both from one slot would mean you cannot raise what a
                // Kill3 pays per target without also inflating every "finish in
                // 14 turns" bonus the generator happened to attach.
                bool conditional = Nz(__result, "RewardGoalType")
                                || Nz(__result, "MaxTurns")
                                || Nz(__result, "MaxAlarmLevel");

                var adj = conditional ? ov.Sec : ov.Obj;
                if (adj == null || adj.Kind == AdjustKind.None) return;

                var idRaw = Get(__result, "Id");
                var qRaw = Get(__result, "RewardQuantity");
                if (idRaw == null || qRaw == null) return;

                long rowId = Convert.ToInt64(idRaw, CultureInfo.InvariantCulture);
                double current = Convert.ToDouble(qRaw, CultureInfo.InvariantCulture);

                double original;
                if (!OriginalQuantity.TryGetValue(rowId, out original))
                {
                    original = current;
                    OriginalQuantity[rowId] = original;
                }

                // The snapshot is scaled as a double and rounded only if the
                // column is integral. It used to be rounded to a long before the
                // adjustment as well as after, which threw away the fractional
                // part of a float RewardQuantity twice over.
                double after = adj.Apply(original, Integral(__result, "RewardQuantity"));
                if (after == current) return;

                Set(__result, "RewardQuantity", after);
            }
            catch (Exception e) { Once("objective", e); }
        }

        // ---- per-type overrides ---------------------------------------------

        // One entry per MissionTypeId. "shipped" is documentation for the reader
        // and is deliberately not deserialised — the engine never reads it, so
        // editing it changes nothing and stale values there cannot mislead the
        // plugin, only you.
        private sealed class MissionOverride
        {
            [JsonPropertyName("type")]            public string Type { get; set; }
            [JsonPropertyName("note")]            public string Note { get; set; }
            [JsonPropertyName("BonusPayment")]    public string BonusPayment { get; set; }
            [JsonPropertyName("BonusExperience")] public string BonusExperience { get; set; }
            [JsonPropertyName("PowerLevelBonus")] public string PowerLevelBonus { get; set; }

            // Scales the mission's OWN cash objective terms: the per-file and
            // per-target payments that are part of what the job is. Measured at
            // 30% of the full job payment each. These rows carry no condition —
            // no goal, no turn limit, no alarm ceiling.
            [JsonPropertyName("ObjectivePayment")] public string ObjectivePayment { get; set; }

            // Scales CONDITIONAL cash rewards — the randomly generated secondary
            // objectives that pay credits: "finishing in 14 turns", "killing at
            // least 12 targets". Same reward type as the above, which is why
            // they need separating: one lever for what the job pays, another for
            // optional bonuses on top.
            [JsonPropertyName("SecondaryPayment")] public string SecondaryPayment { get; set; }

            internal Adjust Pay, Exp, Pl, Obj, Sec;

            internal bool Active =>
                   (Pay != null && Pay.Kind != AdjustKind.None)
                || (Exp != null && Exp.Kind != AdjustKind.None)
                || (Pl  != null && Pl.Kind  != AdjustKind.None)
                || (Obj != null && Obj.Kind != AdjustKind.None)
                || (Sec != null && Sec.Kind != AdjustKind.None);
        }

        private sealed class MissionFile
        {
            // RETIRED 2026-09-13. This used to be
            //     [JsonPropertyName("enabled")] public bool Enabled { get; set; } = true;
            // with the comment "3.0: the subsystem switch lives here now.
            // [MissionRewards] Enabled is gone from ckf.hardmode.cfg and this is
            // the whole enable chain." That is reversed: the switch is back in
            // ckf.hardmode.cfg, as [Slices] MissionRewards (design.md section
            // 3). The key is still parsed so an existing document is not
            // refused; nothing branches on it.
            [JsonPropertyName("enabled")]
            public bool? RetiredEnabled { get; set; }

            [JsonPropertyName("missions")]
            public List<MissionOverride> Missions { get; set; } = new List<MissionOverride>();
        }

        // 3.0: the text comes from ConfigDoc. Only the source moved.
        private static void LoadOverrides()
        {
            var path = ConfigDoc.Where(ConfigDoc.Missions);
            try
            {
                var text = ConfigDoc.SectionText(ConfigDoc.Missions);
                if (text == null)
                {
                    // Since 3.0 this section carries the subsystem switch too,
                    // so an absent one costs the switch as well as the amounts
                    // and `enabled` stays false. An absent section is still an
                    // ordinary configuration — no per-type override is a
                    // supported state — but a document that could not be READ
                    // is not, and reporting the second at Info would be an
                    // instrument going quiet. AGENTS.md §3.
                    var why = $"MissionRewards: {ConfigDoc.WhyNo(ConfigDoc.Missions)}, and there "
                        + "is no pattern-bucket layer behind it any more, so nothing will be "
                        + "adjusted and no hook is installed.";
                    if (ConfigDoc.CouldNotRead(ConfigDoc.Missions)) Plugin.Log.LogError(why);
                    else Plugin.Log.LogInfo(why);
                    return;
                }

                var opts = new JsonSerializerOptions
                {
                    ReadCommentHandling = JsonCommentHandling.Skip,
                    AllowTrailingCommas = true
                };
                var file = JsonSerializer.Deserialize<MissionFile>(text, opts);

                if (file != null)
                    Slices.ReportRetiredGate("MissionRewards", ConfigDoc.Missions,
                                             "MissionRewards", file.RetiredEnabled);
                enabled = true;

                foreach (var m in file?.Missions ?? new List<MissionOverride>())
                {
                    if (string.IsNullOrWhiteSpace(m.Type)) continue;
                    var key = m.Type.Trim();

                    m.Pay = Adjust.Parse(m.BonusPayment);
                    m.Exp = Adjust.Parse(m.BonusExperience);
                    m.Pl  = Adjust.Parse(m.PowerLevelBonus);
                    m.Obj = Adjust.Parse(m.ObjectivePayment);
                    m.Sec = Adjust.Parse(m.SecondaryPayment);

                    if (ByType.ContainsKey(key))
                        Plugin.Log.LogWarning($"MissionRewards: '{key}' is listed twice in "
                            + "the missions file; the later entry wins.");
                    ByType[key] = m;
                }

                foreach (var o in ByType.Values.Where(x => x.Active))
                    Plugin.Log.LogInfo($"MissionRewards: override {o.Type} —"
                        + Describe("pay", o.Pay) + Describe("xp", o.Exp) + Describe("pl", o.Pl)
                        + Describe("objpay", o.Obj) + Describe("secpay", o.Sec));
            }
            catch (Exception e)
            {
                enabled = false;
                Plugin.Log.LogError($"MissionRewards: failed to read {path}: {e.Message}. "
                    + "No per-type overrides are active and no hook is installed.");
            }
        }

        // True when a field is present and non-zero.
        private static bool Nz(object row, string field)
        {
            var v = Get(row, field);
            if (v == null) return false;
            try { return Convert.ToDouble(v, CultureInfo.InvariantCulture) != 0; }
            catch { return false; }
        }

        private static string Describe(string label, Adjust a)
        {
            if (a == null || a.Kind == AdjustKind.None) return "";
            switch (a.Kind)
            {
                case AdjustKind.Set:      return $" {label}={a.Value:0.###}";
                case AdjustKind.Add:      return $" {label}{(a.Value >= 0 ? "+" : "")}{a.Value:0.###}";
                case AdjustKind.Multiply: return $" {label} x{a.Value:0.###}";
                default: return "";
            }
        }

        // ---- adjust expressions ---------------------------------------------

        // INTERNAL, not private, since 2026-09-13 (Phase 5).
        //
        // gui/serve.py's parse_adjust and app.html's JavaScript twin are both
        // explicit transcriptions of Adjust.Parse below, tested against one
        // shared case table. GearClasses needs the same grammar for its lever
        // cells, and a FOURTH copy of a parser that already exists three times
        // is how the copies start disagreeing. Widening the visibility of the
        // one that owns it is the smaller change: no behaviour moves, and
        // MissionRewards remains the only place the grammar is defined.
        internal enum AdjustKind { None, Set, Add, Multiply }

        internal sealed class Adjust
        {
            public static readonly Adjust None = new Adjust { Kind = AdjustKind.None };

            public AdjustKind Kind;
            public double Value;

            // Works in double so a float column can receive a fractional
            // result. `integral` says the destination stores whole numbers; on
            // those the arithmetic is done exactly as the old long-only version
            // did it, so no shipped number moves:
            //
            //   Set       rounds the value here, as (long)Math.Round did.
            //   Add       rounds the ADDEND here, not the result — 1 with
            //             "+1.5" gives 3, which is what the old code produced
            //             and what rounding the result afterwards would not.
            //   Multiply  is left unrounded here; the conversion in Set() rounds
            //             the product, which is where
            //             (long)Math.Round(current * Value) rounded it.
            //
            // On a float or double column nothing is rounded at any step.
            public double Apply(double current, bool integral)
            {
                switch (Kind)
                {
                    case AdjustKind.Set: return integral ? Math.Round(Value) : Value;
                    case AdjustKind.Add:
                        return integral ? current + Math.Round(Value) : current + Value;
                    case AdjustKind.Multiply: return current * Value;
                    default: return current;
                }
            }

            // "" none | "=40" or "40" set | "+25" / "-25" add | "x1.5" / "*1.5" multiply
            // THREE-STATE, added 2026-09-13 (Phase 5).
            //
            // Parse(spec) answers None for a blank cell AND for a cell holding
            // text the grammar rejects, which makes the two indistinguishable
            // to a caller. That is survivable here — MissionRewards logs the
            // rejection itself and carries on — but a lever sheet has to tell
            // "this column is not tuned" from "somebody typed 1.8x instead of
            // x1.8", because the second is a tuning change that silently did
            // not happen. Overlays.BuildRule grew a three-state LineResult for
            // the same reason in Phase 4.
            //
            // The one-argument form is unchanged in behaviour, logs exactly
            // what it logged before, and is still what MissionRewards calls.
            public static Adjust Parse(string spec)
            {
                bool ok;
                var a = Parse(spec, out ok);
                if (!ok)
                    Plugin.Log.LogWarning($"MissionRewards: could not parse adjustment "
                        + $"'{spec}' — expected blank, =N, +N, -N or xN. Ignoring it.");
                return a;
            }

            /// <summary><paramref name="ok"/> is false ONLY for a cell that
            /// carried text the grammar rejects. A blank cell returns None with
            /// ok true. The caller owns the diagnostic, so it can name its own
            /// sheet, row and column.</summary>
            public static Adjust Parse(string spec, out bool ok)
            {
                ok = true;
                spec = (spec ?? "").Trim();
                if (spec.Length == 0) return None;

                var kind = AdjustKind.Set;
                var body = spec;

                if (spec[0] == '=') { kind = AdjustKind.Set; body = spec.Substring(1); }
                else if (spec[0] == 'x' || spec[0] == 'X' || spec[0] == '*')
                { kind = AdjustKind.Multiply; body = spec.Substring(1); }
                else if (spec[0] == '+') { kind = AdjustKind.Add; body = spec.Substring(1); }
                else if (spec[0] == '-') { kind = AdjustKind.Add; body = spec; }

                if (!double.TryParse(body.Trim(), NumberStyles.Float,
                                     CultureInfo.InvariantCulture, out double v))
                {
                    ok = false;
                    return None;
                }
                return new Adjust { Kind = kind, Value = v };
            }
        }

        // ---- plumbing --------------------------------------------------------

        private static readonly Dictionary<string, Type> TypeCache =
            new Dictionary<string, Type>(StringComparer.Ordinal);

        private static int Patch(Harmony harmony, string typeName, string methodName,
                                 string prefixName, string postfixName)
        {
            Type t;
            if (!TypeCache.TryGetValue(typeName, out t))
            {
                t = AccessTools.TypeByName(typeName);
                TypeCache[typeName] = t;
            }
            if (t == null)
            {
                Plugin.Log.LogWarning($"MissionRewards: could not resolve {typeName}.");
                return 0;
            }

            var targets = AccessTools.GetDeclaredMethods(t)
                .Where(m => m.Name == methodName && !m.IsAbstract).ToList();
            if (targets.Count == 0)
            {
                Plugin.Log.LogWarning($"MissionRewards: {t.Name} has no {methodName}.");
                return 0;
            }

            var pre = prefixName == null ? null
                : new HarmonyMethod(AccessTools.Method(typeof(MissionRewards), prefixName));
            var post = postfixName == null ? null
                : new HarmonyMethod(AccessTools.Method(typeof(MissionRewards), postfixName));

            int ok = 0;
            foreach (var m in targets)
            {
                try
                {
                    harmony.Patch(m, prefix: pre, postfix: post);
                    ok++;
                }
                catch (Exception e)
                {
                    Plugin.Log.LogWarning($"MissionRewards: could not hook {t.Name}.{m.Name}: "
                                        + e.Message);
                }
            }
            return ok;
        }

        private const BindingFlags Any = BindingFlags.Public | BindingFlags.NonPublic
                                       | BindingFlags.Instance | BindingFlags.Static;

        private static readonly Dictionary<string, MemberInfo> MemberCache =
            new Dictionary<string, MemberInfo>(StringComparer.Ordinal);

        // Property or field, whichever the game used — the request models mix
        // both and a reader that checked only one would silently return nothing.
        private static MemberInfo Find(object target, string name)
        {
            if (target == null) return null;
            var t = target.GetType();
            var key = t.FullName + "|" + name;
            MemberInfo mi;
            if (MemberCache.TryGetValue(key, out mi)) return mi;

            // DeclaredOnly is what makes this a real per-level walk. Without it
            // GetProperty already searched base types, so the loop added
            // nothing, and a model type that shadowed a base property with `new`
            // threw AmbiguousMatchException. Nearest declaration wins, which is
            // what the loop was written to mean. Same flags PowerLevelCap.PropOf
            // and ModelRules.Prop use.
            //
            // The resolution is guarded here rather than at the call sites: that
            // throw used to escape into the caller's outer catch, where
            // Once("objective", ...) retired every objective payment adjustment
            // for the rest of the session after one warning.
            mi = null;
            for (var cur = t; cur != null && cur != typeof(object) && mi == null; cur = cur.BaseType)
            {
                try
                {
                    mi = (MemberInfo)cur.GetProperty(name, Any | BindingFlags.DeclaredOnly)
                      ?? cur.GetField(name, Any | BindingFlags.DeclaredOnly);
                }
                catch { }
            }
            MemberCache[key] = mi;
            return mi;
        }

        private static object Get(object target, string name)
        {
            var mi = Find(target, name);
            if (mi == null) return null;
            try
            {
                var p = mi as PropertyInfo;
                if (p != null) return p.CanRead ? p.GetValue(target) : null;
                return ((FieldInfo)mi).GetValue(target);
            }
            catch { return null; }
        }

        // Takes a double. The conversion to the column's own type happens here:
        // Accessor.SetNumber rounds an integral target to nearest with halves to
        // even — exactly what Convert.ChangeType did on this path before — and
        // converts straight across for a float or double column, so a fractional
        // value survives. A field, or a property the Accessor could not resolve,
        // goes through Convert.ChangeType, which rounds the same way.
        // One line per (type, column, reason), matching the idiom ModelRules
        // uses for the same class of failure.
        private static readonly HashSet<string> WriteComplaints =
            new HashSet<string>(StringComparer.Ordinal);

        private static void Set(object target, string name, double value)
        {
            var mi = Find(target, name);
            if (mi == null) return;
            try
            {
                var p = mi as PropertyInfo;
                if (p != null)
                {
                    if (!p.CanWrite) return;

                    var acc = Accessors.Get(target.GetType(), name);
                    if (acc != null && acc.Exists && acc.Numeric && acc.CanWrite)
                    {
                        // SetNumber reports WHY it failed rather than a bare
                        // false, so an overflow is no longer indistinguishable
                        // from "the rule changed nothing". Say it once and stop:
                        // falling through to reflection would only repeat the
                        // same conversion and the same failure.
                        var wr = acc.SetNumber(target, value);
                        if (wr == WriteResult.Ok) return;
                        if (WriteComplaints.Add(target.GetType().Name + "|" + name + "|" + wr))
                            Plugin.Log.LogWarning($"MissionRewards: could not write {value} to "
                                + $"{target.GetType().Name}.{name}: {Accessors.Why(wr, acc)}. "
                                + "That adjustment is not being applied. Reported once.");
                        return;
                    }

                    // No Accessor for this property — fall through to reflection
                    // rather than returning quietly: a throw there reaches Once
                    // and says what went wrong.
                    p.SetValue(target, Convert.ChangeType(value, p.PropertyType,
                                                          CultureInfo.InvariantCulture));
                    return;
                }
                var f = (FieldInfo)mi;
                f.SetValue(target, Convert.ChangeType(value, f.FieldType,
                                                      CultureInfo.InvariantCulture));
            }
            catch (Exception e) { Once("set:" + name, e); }
        }

        private static string Str(object v)
        {
            if (v == null) return "";
            if (v is float f) return f.ToString("R", CultureInfo.InvariantCulture);
            if (v is double d) return d.ToString("R", CultureInfo.InvariantCulture);
            if (v is string s) return s;
            if (v is IFormattable fo) return fo.ToString(null, CultureInfo.InvariantCulture);
            return v.ToString();
        }

        private static readonly HashSet<string> Complained =
            new HashSet<string>(StringComparer.Ordinal);

        private static void Once(string where, Exception e)
        {
            if (!Complained.Add(where)) return;
            Plugin.Log.LogWarning($"MissionRewards: {where} failed and will stay quiet from "
                                + $"here: {e.GetType().Name}: {e.Message}");
        }
    }
}
