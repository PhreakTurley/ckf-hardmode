// Slices — every toggle in ckf.hardmode.cfg, bound once, read from one place.
//
// WHY THIS FILE EXISTS
//
// A gate cannot live inside the file it gates. Until this change the eight
// subsystem gates were an "enabled" key at the root of their own section of
// ckf.hardmode.json, so turning a subsystem off meant editing the file that
// turning it off was supposed to stop being read — and a syntax error anywhere
// in that document cost every subsystem its switch as well as its settings
// (ConfigDoc.cs's header says so). ckf.hardmode.cfg is the one file that has to
// parse before any other loading happens, so that is where every gate goes.
// split-config-into-toggleable-slices design.md section 3.
//
// WHAT A SLICE IS. The unit a player turns on and off: one toggle, one concern.
// Most slices are one file; a talent pack is two or three, because its rows are
// rows of two or three game tables and the overlay dialect keys the target
// table off the filename (design.md section 2). Nine slices are not files at
// all — they are the nine sections of ckf.hardmode.json, and their toggle is
// now a .cfg key rather than a field inside the section.
//
// EVERY KEY IS BOUND, EAGERLY, ON EVERY LAUNCH.
//
// CORRECTION, 2026-09-13. Plugin.Binds.g.cs's class doc still says:
//
//     "Bind is still a real ConfigFile.Bind call made at the same point in
//      startup as the hand-written call it replaced: BepInEx writes the file
//      from the set of keys actually bound, and a key nothing binds is left in
//      place as an orphan. Binding every key eagerly would change that, so this
//      class does not do it."
//
// That paragraph described the state in which the table declared 22 keys and
// Plugin.cs bound exactly one of them. It is stale as of this change and the
// wrong half is the last sentence: Slices.Init below binds all 43, because
// design.md section 3 requires every toggle to be a line in ckf.hardmode.cfg
// and BepInEx only writes a line for a key something bound. The paragraph lives
// in scripts/gen_binds.py's HEADER and has to be corrected there, in the
// generator, not here and not in the generated file.
//
// ORDER. Init runs ABOVE the [General] Enabled bail-out in Plugin.Load, not
// below it. Binding below would mean a player who sets Enabled = false on a
// fresh install never gets the 42 [Slices] lines written at all, so the config
// editor would have nothing to show and schema/check_schema.py would report
// them MISSING. Binding above costs 43 dictionary writes on a launch that then
// does nothing else.
//
// AN UNREADABLE GATE IS NOT AN OFF GATE. AGENTS.md section 3. A key whose bind
// throws is recorded Unknown, reported at Error by name, and treated as ON —
// because a silent "off" here would turn a player's tuning off and look exactly
// like them having turned it off themselves. design.md section 3 makes the same
// choice for enable_index: "An unreadable gate is unknown, never off."
//
// SAMPLING MOMENTS. This instrument has exactly three, all at load:
//
//   1. Init()             once, per launch, above the master-switch bail-out.
//   2. VerdictForOverlay  once per file in ckf.hardmode.d, before the file is
//                         opened.
//   3. ReportRetiredGate  once per subsystem section, when that subsystem reads
//                         its section out of ckf.hardmode.json.
//
// There is NO sampling moment after load. Nothing re-reads ckf.hardmode.cfg,
// so an edit made while the game is running is not seen and is not reported as
// unseen either. Relaunching is the only way a toggle takes effect.

using System;
using System.Collections.Generic;
using System.Linq;
using BepInEx.Configuration;

namespace CKFHardMode
{
    internal static class Slices
    {
        /// <summary>The section every slice toggle lives in. [General] Enabled
        /// keeps its own section and its own name — a player's existing .cfg
        /// must still turn the mod off after the upgrade.</summary>
        internal const string Section = "Slices";

        internal enum Gate
        {
            On,        // bound, true
            Off,       // bound, false
            Unknown    // the bind threw; reported at Error, treated as On
        }

        // Slices.<Key> -> gate. Filled by Init from Binds.All, so this class
        // cannot drift from the generated table: every declared key is bound
        // and nothing else is.
        private static readonly Dictionary<string, Gate> gates =
            new Dictionary<string, Gate>(StringComparer.Ordinal);

        private static bool ran;

        internal static int Declared { get; private set; }
        internal static int OnCount { get; private set; }
        internal static int OffCount { get; private set; }
        internal static int UnknownCount { get; private set; }

        // ---- the file table ---------------------------------------------------
        //
        // Overlay filename -> the slice key that gates it. Transcribed from the
        // "Files this toggle gates:" block in each schema's `doc` array, which
        // is where the pairing is declared; schema/ is not this phase's file to
        // edit, so this table is a copy of a declaration rather than a second
        // declaration. 54 files across 33 slices [measured, schema/*.schema.json
        // 2026-09-13], plus ONE row no schema declares -- the
        // MissionPowerLevelModel mirror, whose own comment below says why.
        //
        // CORRECTION, 2026-09-13 (Phase 3). This block used to end: "55 files
        // across 34 slices. Eight of the nine subsystem slices name no file;
        // Progression is the exception, through that mirror." Both sentences
        // were true only while the nine subsystems shared one file that no
        // slice could claim. Phase 3 gave each of them its own file in
        // ckf.hardmode.d, so all nine name a file now and the table is 64 files
        // across 42 slices. The mirror row is still the one row no schema
        // declares.
        //
        // MOST OF THESE FILES DO NOT EXIST YET. They arrive in Phases 4 through
        // 8. The ten that do exist are the nine subsystem settings files and
        // implants-global.json, written in Phase 3. A name here that never
        // appears on disk costs nothing; a file on disk with no entry here is
        // reported as unclaimed rather than silently skipped, which is the half
        // that matters.
        //
        // THE TEN SETTINGS FILES ARE IN THIS TABLE AND ARE NOT OVERLAY FILES.
        // ConfigDoc reads them; Overlays skips them by name before it opens
        // them (ConfigDoc.OwnsFile), because a settings file deserialised as a
        // RuleFile yields zero rules and no error. They are listed here anyway
        // for the other reader of this member: scripts/validate_rules.py
        // --enabled-set parses this table at run time to decide which files the
        // enabled set contains, and a settings file absent from it would be
        // reported as claimed by no slice.
        //
        // OrdinalIgnoreCase: the names come off a Windows filesystem, and a
        // case difference must not quietly unclaim a file and hand it the
        // always-on path.
        private static readonly Dictionary<string, string> OverlayOwner =
            new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
        {
            { "EffectModel.aex.csv",        "TalentsAEX" },
            { "EffectModel.ck.csv",         "TalentsCyberKnight" },
            { "EffectModel.cs.csv",         "TalentsCS" },
            { "EffectModel.gs.csv",         "TalentsGunslinger" },
            { "EffectModel.sc.csv",         "TalentsSawbones" },
            { "EffectModel.sn.csv",         "TalentsSniper" },
            { "EffectModel.sol.csv",        "TalentsSoldier" },
            { "EffectModel.vg.csv",         "TalentsVanguard" },
            { "EffectModel.wg.csv",         "TalentsWraith" },
            { "EffectModel.wm.csv",         "TalentsWarMachine" },
            { "JobNodeModel.aex.csv",       "TalentsAEX" },
            { "JobNodeModel.ck.csv",        "TalentsCyberKnight" },
            { "JobNodeModel.cs.csv",        "TalentsCS" },
            { "JobNodeModel.gs.csv",        "TalentsGunslinger" },
            { "JobNodeModel.hkr.csv",       "TalentsHacker" },
            { "JobNodeModel.sc.csv",        "TalentsSawbones" },
            { "JobNodeModel.sn.csv",        "TalentsSniper" },
            { "JobNodeModel.sol.csv",       "TalentsSoldier" },
            { "JobNodeModel.vg.csv",        "TalentsVanguard" },
            { "JobNodeModel.wg.csv",        "TalentsWraith" },
            { "JobNodeModel.wm.csv",        "TalentsWarMachine" },
            { "MatrixEffectModel.hkr.csv",  "TalentsHacker" },
            // ADDED 2026-09-13, and it is NOT one of the 54 rows the schemas'
            // "Files this toggle gates:" blocks declare. gen_teampl_labels.py
            // generates this file from teampl.override merged over teampl.table,
            // which is Progression's own data, and teampl.schema.json's
            // linkedEnable `reason` describes the ungated state as "a stock
            // award with a lying label. Neither direction logs anything."
            // design.md section 2 lists it under "enemy gear, unchanged" and is
            // wrong on both counts; section 1 names it as this subsystem's
            // mirror. The coordinator is correcting section 2.
            { "MissionPowerLevelModel.generated.json", "Progression" },
            { "RuleModel.csv",              "RuleModel" },
            { "TalentModel.aex.csv",        "TalentsAEX" },
            { "TalentModel.ck.csv",         "TalentsCyberKnight" },
            { "TalentModel.cs.csv",         "TalentsCS" },
            { "TalentModel.gs.csv",         "TalentsGunslinger" },
            { "TalentModel.hkr.csv",        "TalentsHacker" },
            { "TalentModel.sc.csv",         "TalentsSawbones" },
            { "TalentModel.sn.csv",         "TalentsSniper" },
            { "TalentModel.sol.csv",        "TalentsSoldier" },
            { "TalentModel.vg.csv",         "TalentsVanguard" },
            { "TalentModel.wm.csv",         "TalentsWarMachine" },
            { "consumables-chems.csv",      "ConsumablesChems" },
            // The nine subsystem settings files and the implant globals, added
            // in Phase 3. Read by ConfigDoc, not by Overlays. See the note at
            // the head of this table.
            { "difficulty.json",            "Difficulty" },
            { "elapse.json",                "Elapse" },
            { "fatigue.json",               "Fatigue" },
            { "missions.json",              "MissionRewards" },
            { "modelrules.json",            "ModelRules" },
            { "powerlevel.json",            "PowerLevel" },
            { "rewardcurve.json",           "RewardCurve" },
            { "selfcheck.json",             "SelfCheck" },
            { "teampl.json",                "Progression" },
            { "consumables-devices.csv",    "ConsumablesDevices" },
            { "consumables-grenades.csv",   "ConsumablesGrenades" },
            { "consumables-matrix.csv",     "ConsumablesMatrix" },
            { "consumables-medical.csv",    "ConsumablesMedical" },
            { "consumables-sploitkits.csv", "ConsumablesSploitkits" },
            { "cyberweapons-claws.csv",     "CyberweaponsClaws" },
            { "cyberweapons-lasers.csv",    "CyberweaponsLasers" },
            { "gear-classes.csv",           "GearClasses" },
            { "implants-global.json",       "ImplantsGlobal" },
            { "implants-slot01.csv",        "ImplantsSlot01" },
            { "implants-slot02.csv",        "ImplantsSlot02" },
            { "implants-slot03.csv",        "ImplantsSlot03" },
            { "implants-slot04.csv",        "ImplantsSlot04" },
            { "implants-slot05.csv",        "ImplantsSlot05" },
            { "implants-slot06.csv",        "ImplantsSlot06" },
            { "implants-slot07.csv",        "ImplantsSlot07" },
            { "implants-slot08.csv",        "ImplantsSlot08" },
            { "implants-slot09.csv",        "ImplantsSlot09" },
            { "implants-slot10.csv",        "ImplantsSlot10" },
            { "implants-slot11.csv",        "ImplantsSlot11" },
        };

        // ---- binding ----------------------------------------------------------

        /// <summary>Bind every declared key and say what the .cfg answered.
        ///
        /// Called from Plugin.Load ABOVE the [General] Enabled bail-out, so the
        /// file BepInEx writes carries all 43 lines on every launch including
        /// one where the mod is switched off. See the header on why.
        ///
        /// Returns the [General] Enabled entry, which is the one key with its
        /// own section and the one the caller bails out on.</summary>
        internal static ConfigEntry<bool> Init(ConfigFile config)
        {
            if (ran) return master;
            ran = true;

            var unknownKeys = new List<string>();

            foreach (var def in Binds.All)
            {
                // Every key in the table is a bool today and the generator has
                // no other type for a slice toggle. A non-bool is a defect in
                // the schema, not a configuration a player can reach, so it is
                // named rather than skipped.
                if (def.ValueType != typeof(bool))
                {
                    Plugin.Log.LogError("Slices: \"" + def.Id + "\" is declared "
                        + def.ValueType.Name + " in Plugin.Binds.g.cs, not Boolean. It is NOT "
                        + "bound, so BepInEx writes no line for it and nothing reads it. Fix the "
                        + "schema and re-run scripts/gen_binds.py. Treated as ON for this "
                        + "launch, because nothing read it.");
                    gates[def.Id] = Gate.Unknown;
                    unknownKeys.Add(def.Id);
                    continue;
                }

                try
                {
                    var entry = Binds.Bind<bool>(config, def.Section, def.Key);
                    if (def.Section == "General" && def.Key == "Enabled") master = entry;
                    gates[def.Id] = entry.Value ? Gate.On : Gate.Off;
                }
                catch (Exception e)
                {
                    // NOT "off". Nobody looked. AGENTS.md section 3.
                    gates[def.Id] = Gate.Unknown;
                    unknownKeys.Add(def.Id);
                    Plugin.Log.LogError("Slices: could not bind \"" + def.Id + "\": "
                        + e.GetType().Name + ": " + e.Message + ". That is NOT the same as the "
                        + "key being false — nothing read it — so this slice is treated as ON "
                        + "for this launch rather than silently turned off.");
                }
            }

            Declared = Binds.All.Length;
            OnCount = gates.Values.Count(g => g == Gate.On);
            OffCount = gates.Values.Count(g => g == Gate.Off);
            UnknownCount = gates.Values.Count(g => g == Gate.Unknown);

            // THE SUMMARY LINE. It names the three outcomes separately and
            // names every key that is not On, because a line reporting only a
            // total cannot tell "off" from "there were none" (AGENTS.md section
            // 3). The Off list is what a later "skipped" line is checked
            // against; the Unknown list is what says the instrument could not
            // look.
            var off = gates.Where(kv => kv.Value == Gate.Off)
                           .Select(kv => kv.Key).OrderBy(k => k, StringComparer.Ordinal).ToList();

            var line = "Slices: " + Declared + " key(s) declared in Plugin.Binds.g.cs, "
                     + (Declared - UnknownCount) + " read from ckf.hardmode.cfg — "
                     + OnCount + " on, " + OffCount + " off, " + UnknownCount + " unreadable."
                     + (off.Count == 0 ? " Nothing is switched off."
                                       : " Off: " + string.Join(", ", off) + ".")
                     + (unknownKeys.Count == 0 ? ""
                                       : " Unreadable: " + string.Join(", ", unknownKeys)
                                       + " — see the error(s) above.");

            if (UnknownCount > 0) Plugin.Log.LogError(line);
            else Plugin.Log.LogInfo(line);

            if (master == null)
                Plugin.Log.LogError("Slices: [General] Enabled was not bound. The master switch "
                    + "is the one key that has to work when everything else on disk is broken; "
                    + "the mod runs as if it were true this launch.");

            return master;
        }

        private static ConfigEntry<bool> master;

        // ---- reading a gate ---------------------------------------------------

        /// <summary>The gate for one slice key, named without its section:
        /// Of("Fatigue") reads [Slices] Fatigue.</summary>
        internal static Gate Of(string key)
        {
            Gate g;
            if (gates.TryGetValue(Section + "." + key, out g)) return g;

            // Init has not run, or the key is not in the generated table. Both
            // are defects in this assembly rather than configurations, and both
            // are "could not look".
            Plugin.Log.LogError("Slices: no gate for \"" + Section + "." + key + "\". Either "
                + "Slices.Init has not run yet or scripts/gen_binds.py does not declare that "
                + "key. Treated as ON for this launch.");
            return Gate.Unknown;
        }

        /// <summary>True unless the gate is explicitly false. Unknown is ON —
        /// see the header.</summary>
        internal static bool On(string key)
        {
            return Of(key) != Gate.Off;
        }

        /// <summary>The sentence a subsystem logs when its gate is off. One
        /// wording, so every subsystem's off-line names the same file and the
        /// same key.</summary>
        internal static string OffBecause(string key, string consequence)
        {
            return "[" + Section + "] " + key + " is false in ckf.hardmode.cfg — " + consequence;
        }

        // ---- the retired JSON gates -------------------------------------------

        /// <summary>Report an "enabled" key still sitting at the root of a
        /// subsystem's section of ckf.hardmode.json.
        ///
        /// The eight subsystem gates moved to ckf.hardmode.cfg in Phase 1 of
        /// split-config-into-toggleable-slices. The key is still PARSED, so an
        /// existing document keeps loading instead of being refused for a key
        /// that maps to no member — the same treatment Fatigue.cs already gives
        /// the eight flat settings removed on 2026-09-07. It is not read, and
        /// nothing branches on it: it is a retired key, not a second gate.
        ///
        /// A retired key that is reported by nothing is the silent failure the
        /// unknown-key buckets exist to prevent, and a retired key whose value
        /// is FALSE is worse than that — the player switched something off and
        /// it is now on. That case gets its own sentence.</summary>
        /// <param name="value">null when the section does not carry the key.
        /// </param>
        internal static void ReportRetiredGate(string subsystem, string section,
                                               string sliceKey, bool? value)
        {
            if (value == null) return;

            var head = subsystem + ": the \"" + section + "\" section of " + ConfigDoc.FileName
                     + " still carries \"enabled\": "
                     + (value.Value ? "true" : "false") + ". That key is RETIRED and is not "
                     + "read. The gate is [" + Section + "] " + sliceKey
                     + " in ckf.hardmode.cfg, which is "
                     + (Of(sliceKey) == Gate.Off ? "false"
                        : Of(sliceKey) == Gate.On ? "true" : "unreadable") + ".";

            if (!value.Value && Of(sliceKey) != Gate.Off)
                Plugin.Log.LogError(head + " YOUR SETTING HAS NOT CARRIED OVER: you had this "
                    + "subsystem switched off in the JSON and it is ON this launch. Set ["
                    + Section + "] " + sliceKey + " = false in ckf.hardmode.cfg to switch it "
                    + "off again, then delete the \"enabled\" line from the section.");
            else
                Plugin.Log.LogWarning(head + " Deleting the line changes nothing.");
        }

        // ---- the per-file verdict ---------------------------------------------

        /// <summary>What to do with one file in ckf.hardmode.d, decided BEFORE
        /// the file is opened.</summary>
        internal sealed class Verdict
        {
            /// <summary>False only when a slice claims this file and its gate
            /// is explicitly false.</summary>
            internal bool Open;
            /// <summary>The slice key that claims the file, or null when no
            /// slice does.</summary>
            internal string SliceKey;
        }

        /// <summary>The verdict for one overlay filename. Called once per file,
        /// before the read. A file no slice claims is OPENED — the three enemy
        /// gear overlays and the teampl mirror are in that state today and
        /// turning them off here would be a silent tuning change — and the
        /// caller counts and names them so "nothing claims this" is never
        /// indistinguishable from "a slice claims it and it is on".</summary>
        internal static Verdict VerdictForOverlay(string fileName)
        {
            string key;
            if (fileName == null || !OverlayOwner.TryGetValue(fileName, out key))
                return new Verdict { Open = true, SliceKey = null };

            return new Verdict { Open = Of(key) != Gate.Off, SliceKey = key };
        }
    }
}
