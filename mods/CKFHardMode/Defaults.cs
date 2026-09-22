// Defaults — the config files this mod needs on disk (`Expected`), and
// whether they are there.
//
// The mod is an engine and its content is data. A launch with no
// ckf.hardmode.d directory widens the difficulty sliders and does nothing
// else: Overlays.Load logs "no ckf.hardmode.d directory; nothing to merge"
// and each settings slice reports that it has nothing to read.
//
// The files are not embedded in the DLL. They travel as loose files in the
// release zip, under BepInEx\config\, and extracting the zip is what puts
// them on disk. scripts/make_release.py collects them from the live
// BepInEx\config (or --config DIR) by the names in its CONFIG_FILES, renders
// ckf.hardmode.cfg from release/ckf.hardmode.cfg.in, and refuses to build a
// release that is missing any of them. Retuning the mod is a config edit plus
// make_release.py, with no dotnet build in the loop.
//
// So this class writes nothing (no file, directory, backup or rename). It
// reports whether the extraction landed: Install() checks every path in
// `Expected`, logs one summary line whatever it finds, and names every file
// that is not there. An instrument that only speaks on failure cannot be told
// apart from one that stopped running (AGENTS.md).
//
// What `Expected` holds, all under BepInEx/config:
//
//   ckf.hardmode.cfg                    [General] Enabled + one [Slices] key
//                                       per slice (Slices.cs binds them)
//   ckf.hardmode.selfcheck.csv          the regression suite's input
//   ckf.hardmode.d/ArmorModel.csv       ] enemy-gear overlays no schema claims
//   ckf.hardmode.d/WeaponModel.csv      ]
//   ckf.hardmode.d/MonsterTypeModel.csv ]
//   ckf.hardmode.d/MissionPowerLevelModel.generated.json   the Team PL mirror
//   ckf.hardmode.d/<slice>.json         the ten settings slices ConfigDoc owns
//
// ckf.hardmode.cfg is listed even though BepInEx rewrites it on launch.
// Shipping it means the first launch is not what creates it, and a config
// directory without it means the extraction did not land here.
//
// MissionPowerLevelModel.generated.json is listed because Overlays.Load takes
// .json as well as .csv and loads it as an ordinary rules file. It is what
// makes the victory screen's "Team gained N PL" agree with the award. The ten
// settings slices are skipped by Overlays before it opens them
// (ConfigDoc.OwnsFile) and are reported by ConfigDoc instead.
//
// The other half of this table is CONFIG_FILES in scripts/make_release.py.
// Nothing derives either list from the other; change one and change the
// other. The overlay CSVs owned by content slices are not listed here:
// make_release.py ships them by sweeping ckf.hardmode.d, and
// schema/check_schema.py reports any that are missing.
//
// "NOT THERE" AND "COULD NOT LOOK" ARE DIFFERENT ANSWERS (AGENTS.md). An
// exception out of File.Exists is its own reported outcome and is never
// counted as present.
//
// When [General] Enabled is false, Plugin.Load returns before this call and
// nothing is checked.

using System;
using System.Collections.Generic;
using System.IO;
using BepInEx;

namespace CKFHardMode
{
    internal static class Defaults
    {
        /// <summary>The settings-layout version stamped as "_version" in every
        /// settings slice (ConfigDoc.ReportStamps compares them at launch).
        /// It changes when the SHAPE of a settings file changes, which is what
        /// the stamp is for: a file carrying an older stamp is in an older
        /// layout. Until 4.0.0 that coincided with a public release, so this
        /// tracked Plugin.PluginVersion and the csproj Version; 4.1.0 is the
        /// first bump that does not, and those two are unchanged by it.
        /// scripts/make_release.py reads this literal and refuses a release
        /// where any packaged slice's "_version" disagrees, so every slice is
        /// restamped together even when only one of them changed shape.
        /// 4.1.0: fatigue.json went from two stage blocks with four
        /// byPowerLevel curves to one shared curve, one knight curve and three
        /// tier trait ids.</summary>
        internal const string DocVersion = "4.1.0";

        // Paths under BepInEx/config, forward-slashed. Every entry except
        // ckf.hardmode.cfg is also in CONFIG_FILES in scripts/make_release.py;
        // the .cfg comes from its template.
        private static readonly string[] Expected =
        {
            "ckf.hardmode.cfg",
            "ckf.hardmode.selfcheck.csv",
            ConfigDoc.DirName + "/EffectModel.limitbreak.csv",
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
