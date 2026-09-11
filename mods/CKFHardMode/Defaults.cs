// Defaults — the eight config files this mod needs on disk, and whether they
// are there.
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
// them — CONFIG_FILES there is the table of what ships and where it lands, and
// it refuses to build a release that is missing any of them. Retuning the mod
// is now an edit to a cfg, csv or json plus make_release.py, with no
// dotnet build in the loop.
//
// So there is nothing for this class to write, and one thing left for it to
// say: whether the extraction actually landed. AGENTS.md §3 — an instrument
// that only reports when something went wrong is one that has gone quiet, and
// a config surface with a hole in it is a subsystem that says it has nothing to
// read for a reason nobody connects to the install. Install() checks each of
// the eight paths, logs one summary line whatever it finds, and names every
// file that is not there.
//
// The eight, all under BepInEx/config:
//
//   ckf.hardmode.json                          the merged config document
//   ckf.hardmode.cfg                           one key, [General] Enabled
//   ckf.hardmode.rules.json                    the rule set
//   ckf.hardmode.selfcheck.csv                 the regression suite's input
//   ckf.hardmode.d/ArmorModel.csv              armour overlay rows
//   ckf.hardmode.d/WeaponModel.csv             weapon overlay rows
//   ckf.hardmode.d/MonsterTypeModel.csv        enemy overlay rows
//   ckf.hardmode.d/MissionPowerLevelModel.generated.json   30 label rules
//
// The last one is in the list because Overlays.Load takes .json as well as
// .csv (Overlays.cs:88-90) and loads it as an ordinary rules file. It is what
// makes the victory screen's "Team gained N PL" agree with the award, and it
// is why a good launch reports "Overlays: 4 file(s), 3022 row(s) merged" —
// three CSVs and the mirror. Without it a launch reports 3 files and loses
// those 30 rules with nothing saying so.
//
// ckf.hardmode.cfg is in the list even though BepInEx rewrites it on launch
// from the key Plugin.cs binds. Shipping it means the player's first launch is
// not the thing that creates it, and a config directory without it is still
// worth reporting, because it means the extraction did not land here.
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
        /// refuses a release where it disagrees with the "_version" of
        /// mods/CKFHardMode/defaults/ckf.hardmode.json.</summary>
        internal const string DocVersion = "3.0.0";

        // Paths under BepInEx/config, forward-slashed. The other half of this
        // table is CONFIG_FILES in scripts/make_release.py, which is what puts
        // each of these in the zip. Nothing derives either list from the other;
        // change one and change the other.
        private static readonly string[] Expected =
        {
            ConfigDoc.FileName,
            "ckf.hardmode.cfg",
            "ckf.hardmode.rules.json",
            "ckf.hardmode.selfcheck.csv",
            "ckf.hardmode.d/ArmorModel.csv",
            "ckf.hardmode.d/WeaponModel.csv",
            "ckf.hardmode.d/MonsterTypeModel.csv",
            "ckf.hardmode.d/MissionPowerLevelModel.generated.json",
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
