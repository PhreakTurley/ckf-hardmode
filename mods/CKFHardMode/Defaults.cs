// Defaults — the sixteen config files this mod needs on disk, and whether
// they are there.
//
// WHY THIS FILE EXISTS
//
// The mod is an engine and its content is data. A launch with no config
// document and no ckf.hardmode.d directory widens the difficulty sliders and
// does nothing else: Overlays.Load logs "no ckf.hardmode.d directory; nothing
// to merge" and returns, and an absent document is the same silent nothing one
// section at a time.
//
// The files used to be EmbeddedResources in this DLL, and this class wrote the
// ones that were absent. They are not embedded any more. They travel as loose
// files in the release zip, under BepInEx\config\, and extracting the zip over
// the game folder is what puts them on disk. scripts/make_release.py collects
// them from the live BepInEx\config the config editor edits (or --config DIR);
// the repo holds no copy. CONFIG_FILES there names the seven it copies, the
// .cfg is rendered from release/ckf.hardmode.cfg.in, and it refuses to build a
// release that is missing any of them. Retuning the mod is an edit to the live
// config plus make_release.py, with no dotnet build in the loop.
//
// So there is nothing for this class to write, and one thing left for it to
// say: whether the extraction actually landed. AGENTS.md §3 — an instrument
// that only reports when something went wrong is one that has gone quiet, and
// a config surface with a hole in it is a subsystem that says it has nothing to
// read for a reason nobody connects to the install. Install() checks each of
// the sixteen paths, logs one summary line whatever it finds, and names every
// file that is not there.
//
// The sixteen, all under BepInEx/config:
//
//   ckf.hardmode.cfg                           43 keys (see the correction below)
//   ckf.hardmode.selfcheck.csv                 the regression suite's input
//   ckf.hardmode.d/ArmorModel.csv              armour overlay rows
//   ckf.hardmode.d/WeaponModel.csv             weapon overlay rows
//   ckf.hardmode.d/MonsterTypeModel.csv        enemy overlay rows
//   ckf.hardmode.d/MissionPowerLevelModel.generated.json   30 label rules
//   ckf.hardmode.d/difficulty.json             ] the nine subsystem slices,
//   ckf.hardmode.d/elapse.json                 ] one settings file each,
//   ckf.hardmode.d/fatigue.json                ] tables included
//   ckf.hardmode.d/missions.json               ]
//   ckf.hardmode.d/rewardcurve.json            ]
//   ckf.hardmode.d/teampl.json                 ]
//   ckf.hardmode.d/powerlevel.json             ]
//   ckf.hardmode.d/modelrules.json             ]
//   ckf.hardmode.d/selfcheck.json              ]
//   ckf.hardmode.d/implants-global.json        the THREE implant multipliers
//
// CORRECTION, 2026-09-14 (Phase 9). This table used to carry a second row,
// directly under ckf.hardmode.cfg, and `Expected` below used to carry the
// matching entry:
//
//     ckf.hardmode.rules.json                    the rule set
//
// WHAT THAT FILE WAS. One flat JSONC array of 269 rules -- 263 exact
// selectors, 6 range selectors, 0 unscoped, 76,451 bytes, 2,930 lines --
// read by ModelRules.LoadRules and applied before the overlay directory.
// Per model: EffectModel 129, JobNodeModel 71, TalentModel 42, WeaponModel 17,
// MatrixEffectModel 8, RuleModel 2 [measured, 2026-09-14, on the live file as
// it was deleted].
//
// WHY IT WENT. split-config-into-toggleable-slices converted all 269 into
// ckf.hardmode.d: 238 into the 33 direct-overlay CSVs (scripts/
// rules_to_overlays.py wrote them and compared both compiled sets element by
// element, in order) and the remaining 31 into the shipping lever sheets --
// 22 into cyberweapons-lasers.csv / cyberweapons-claws.csv and 9 into
// implants-slot08.csv. Every one of the 269 rules is `set`-only and exact, so
// the sheets alone land on the same numbers the sheets plus the file did:
// 42,471 (table, id, column) triple(s) compared with the file and without it,
// 0 differences, and all 448 writes the file made matched by an identical
// (operator, value) write from a shipping sheet [measured, 2026-09-14].
//
// WHY THE ROW HAD TO GO WITH IT. Leaving the name in `Expected` after the file
// was deleted made this instrument report a correctly migrated 4.0 install as
// a broken one, at Error, on every launch: "Defaults: missing
// <config>\ckf.hardmode.rules.json" and a summary reading 16 of 17
// [measured on a 4.0 zip built 2026-09-14, scripts/make_release.py
// NOT_SHIPPED_BUT_EXPECTED]. That is the same failure the Phase 3 correction
// below describes, in the other direction.
//
// THE ABSENCE IS STILL REPORTED, JUST NOT AS A FAULT. Plugin.Load states which
// of the two layouts it found before it calls ModelRules.Init, and
// ModelRules.LoadRules names the file when it is not there rather than
// returning quietly. A rules file that COMES BACK is the loud case now.
//
// STILL OPEN, AND NOT THIS FILE'S TO CLOSE. scripts/make_release.py's
// NOT_SHIPPED_BUT_EXPECTED still names ckf.hardmode.rules.json, and its
// selftest section [2c] is armed to go RED the day this array loses the name.
// It has. That tripwire fired as designed; scripts/ is outside this commit's
// file boundary, so it is reported rather than silenced.
//
// CORRECTION, 2026-09-13 (Phase 3). This table used to open "The eight, all
// under BepInEx/config" and its first row was
//
//     ckf.hardmode.json                          the merged config document
//
// That file is the PRE-4.0 layout and IS NO LONGER EXPECTED. Leaving it in the
// list would have made this instrument report a correctly migrated install as
// a broken one, at Error, on every launch -- and leaving the ten slice files
// OUT of the list would have made it report a missing one as nothing at all,
// which is the failure this class exists to prevent. Both halves moved
// together. split-config-into-toggleable-slices Phase 3.
//
// MissionPowerLevelModel.generated.json is in the list because Overlays.Load
// takes .json as well as .csv (Overlays.cs, member Load) and loads it as an
// ordinary rules file. It is what makes the victory screen's "Team gained N
// PL" agree with the award, and it is why a good launch reports "Overlays: 4
// file(s), 3022 row(s) merged" — three CSVs and the mirror. Without it a launch
// reports 3 files and loses those 30 rules with nothing saying so.
//
// CORRECTION, 2026-09-13 (Phase 3). That paragraph used to open "The last one"
// and cite Overlays.cs:88-90. It is no longer last in the table -- ten slice
// files were appended below it -- and the line numbers went stale the moment
// Overlays.cs was edited, which is why the citation is now the member.
//
// THE TEN SLICE FILES ARE NOT IN THAT COUNT. Overlays skips them by name
// before opening them (Overlays.cs, member Load, via ConfigDoc.OwnsFile), so
// "4 file(s) read" stays 4 and they are named on a line of their own. ConfigDoc
// is what reports on them.
//
// ckf.hardmode.cfg is in the list even though BepInEx rewrites it on launch
// from the keys Plugin.cs binds. Shipping it means the player's first launch is
// not the thing that creates it, and a config directory without it is still
// worth reporting, because it means the extraction did not land here.
//
// CORRECTION, 2026-09-13. The table above used to describe ckf.hardmode.cfg as
// "one key, [General] Enabled", and the paragraph above said "the key Plugin.cs
// binds", singular. Both were true until this date and neither is now: the file
// carries 43 keys, [General] Enabled plus one [Slices] key per slice, and
// Slices.Init binds all of them (split-config-into-toggleable-slices design.md
// section 3). Nothing about THIS class changed — it counts files, not keys —
// but the description of the file it counts was wrong and would have been read
// as fact by the next reader.
//
// CORRECTION, 2026-09-13 (Phase 3). The paragraph here used to read: "The
// eight paths below are unchanged by that. The slice files this change
// introduces arrive in Phases 4 through 8 and are added to `Expected` then,
// alongside CONFIG_FILES in scripts/make_release.py." The first sentence is
// no longer true -- Phase 3 changed the paths, see the table above -- and the
// second was only ever true of Phases 4 through 8's files. Phase 3's ten
// arrived first.
//
// CONFIG_FILES in scripts/make_release.py IS STILL THE OTHER HALF OF THIS
// TABLE AND HAS NOT BEEN UPDATED. scripts/ is outside Phase 3's file boundary,
// so that list still names ckf.hardmode.json and none of the ten. A release
// built before it is updated would package the old layout. Nothing derives
// either list from the other; this comment is the only thing connecting them.
//
// THIS CLASS WRITES NOTHING. It does not create a file, a directory, a backup
// or a rename. Every outcome it has is a log line.
//
// "NOT THERE" AND "COULD NOT LOOK" ARE DIFFERENT ANSWERS. AGENTS.md §3. An
// exception out of File.Exists is its own reported outcome and is never counted
// as present — a directory the process cannot read would otherwise report a
// complete config surface it never actually saw.
//
// WHEN THE MOD IS OFF, NOTHING IS CHECKED. Plugin.Load returns above this call
// when [General] Enabled is false, which is the same place it always returned.

using System;
using System.Collections.Generic;
using System.IO;
using BepInEx;

namespace CKFHardMode
{
    internal static class Defaults
    {
        /// <summary>The LAYOUT version of ckf.hardmode.json, which is not
        /// Plugin.PluginVersion and must not be. The plugin version moves on
        /// every build; this one moves only when the document's shape does.
        /// scripts/make_release.py reads this literal out of this file and
        /// refuses a release where it disagrees with the "_version" of the
        /// ckf.hardmode.json it packages from the live config.</summary>
        internal const string DocVersion = "4.0.0";

        // Paths under BepInEx/config, forward-slashed. The other half of this
        // table is CONFIG_FILES in scripts/make_release.py, which puts seven of
        // these in the zip; ckf.hardmode.cfg comes from its template. Nothing
        // derives either list from the other; change one and change the other.
        private static readonly string[] Expected =
        {
            "ckf.hardmode.cfg",
            "ckf.hardmode.selfcheck.csv",
            ConfigDoc.DirName + "/ArmorModel.csv",
            ConfigDoc.DirName + "/WeaponModel.csv",
            ConfigDoc.DirName + "/MonsterTypeModel.csv",
            ConfigDoc.DirName + "/MissionPowerLevelModel.generated.json",
            ConfigDoc.DirName + "/" + ConfigDoc.FileFor(ConfigDoc.Difficulty),
            ConfigDoc.DirName + "/" + ConfigDoc.FileFor(ConfigDoc.Elapse),
            ConfigDoc.DirName + "/" + ConfigDoc.FileFor(ConfigDoc.Fatigue),
            ConfigDoc.DirName + "/" + ConfigDoc.FileFor(ConfigDoc.Missions),
            ConfigDoc.DirName + "/" + ConfigDoc.FileFor(ConfigDoc.RewardCurve),
            ConfigDoc.DirName + "/" + ConfigDoc.FileFor(ConfigDoc.TeamPl),
            ConfigDoc.DirName + "/" + ConfigDoc.FileFor(ConfigDoc.PowerLevel),
            ConfigDoc.DirName + "/" + ConfigDoc.FileFor(ConfigDoc.ModelRules),
            ConfigDoc.DirName + "/" + ConfigDoc.FileFor(ConfigDoc.SelfCheck),
            ConfigDoc.DirName + "/" + ConfigDoc.FileFor(ConfigDoc.ImplantsGlobal),
        };

        private static bool ran;

        /// <summary>Called from Plugin.Load, below the master-switch bail-out
        /// and ABOVE ConfigDoc.Init(), so that what is and is not on disk is
        /// stated before anything tries to read it.</summary>
        internal static void Install()
        {
            if (ran) return;
            ran = true;

            var dir = Paths.ConfigPath;

            var missing = new List<string>();     // looked, not there
            var unknown = new List<string>();     // could not look
            int present = 0;

            foreach (var rel in Expected)
            {
                var path = Path.Combine(dir, rel.Replace('/', Path.DirectorySeparatorChar));
                try
                {
                    if (File.Exists(path)) present++;
                    else missing.Add(path);
                }
                catch (Exception e)
                {
                    // Not "not there": nobody looked. Reported as its own
                    // outcome and counted with neither of the other two.
                    unknown.Add(path);
                    Plugin.Log.LogError($"Defaults: could not tell whether {path} exists: "
                        + $"{e.GetType().Name}: {e.Message}");
                }
            }

            var summary = $"Defaults: {present} of {Expected.Length} config file(s) present.";
            if (missing.Count > 0)
                summary += $" {missing.Count} missing.";
            if (unknown.Count > 0)
                summary += $" {unknown.Count} could not be checked.";

            if (missing.Count == 0 && unknown.Count == 0)
            {
                Plugin.Log.LogInfo(summary);
                return;
            }

            Plugin.Log.LogError(summary);

            foreach (var path in missing)
                Plugin.Log.LogError($"Defaults: missing {path}");
            foreach (var path in unknown)
                Plugin.Log.LogError($"Defaults: not checked {path}");

            Plugin.Log.LogError("Defaults: this mod ships those files in its zip and does not "
                + "write them. The subsystems that needed them will say they have nothing to "
                + "read, below. To put them back, extract the release zip's BepInEx\\config "
                + "folder over your game folder again; that overwrites the settings files with "
                + "the shipped ones, so copy anything you have retuned somewhere else first.");
        }
    }
}
