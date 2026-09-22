// ConfigDoc — one settings file per slice, read once.
//
// No slice's settings live in a file another slice can disable, so one syntax
// error costs one slice its settings and no other slice anything. The switches
// are in ckf.hardmode.cfg (Slices.cs), never in these files.
//
// The layout this class reads:
//
//     BepInEx/config/ckf.hardmode.d/
//       difficulty.json   elapse.json    fatigue.json
//       missions.json     rewardcurve.json  teampl.json
//       powerlevel.json   modelrules.json   selfcheck.json
//       implants-global.json
//
// Each file is { "_version": "<Defaults.DocVersion>", ...that slice's keys... }.
// Each loader deserialises its own whole object; this class only supplies the
// text. `SectionText` hands back the file's JSON body minus "_version", so the
// loader's own JsonSerializer call, its [JsonExtensionData] bag, its defaulting
// and its error paths all apply.
//
// `FileName` names ckf.hardmode.json, the pre-4.0 single-file layout. It is
// never read for settings; only the both-layouts refusal below uses it.
//
// THE STRAY-KEY GUARD
//
// A misspelled key or file must not be silently ignored. Two shapes:
//
//   1. A stray KEY inside a slice file. Checked here against that slice's own
//      declared keys (transcribed below from each schema's `fields`, plus the
//      retired "enabled" gate) and reported at Error by name. The file's text
//      is STILL SERVED, so the loader's own extension-data bag reports it too
//      and refuses the file. Checking here as well means the guard runs on a
//      launch where the subsystem is switched off and its loader never asks
//      (AGENTS.md: a guard that only runs when someone asks can go quiet).
//
//   2. A misspelled FILE. There is no loader for elapes.json, so the summary
//      line names every expected slice file that is not on disk, every
//      launch. Overlays names it from the other side, on its "claimed by no
//      slice" line.
//
// A DUPLICATE TOP-LEVEL KEY IS AN ERROR. JSON last-wins discards the earlier
// one, so a player who edited the first of two "curve" keys has edited nothing.
//
// BOTH LAYOUTS PRESENT IS A REFUSAL. If ckf.hardmode.json is on disk and any
// slice file is too, this class sets `BothLayouts` and Plugin.Load applies
// nothing this launch. Silently preferring one layout would mean a player's
// tuning quietly stops applying.
//
// "The file is not there" and "the file could not be read" are different
// findings and get different sentences (AGENTS.md). `WhyNo` says which, and
// `CouldNotRead(section)` decides whether the caller logs Warning or Error.
// State is per file, so that answer takes the slot it is about.

using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Text.Json;
using BepInEx;

namespace CKFHardMode
{
    internal static class ConfigDoc
    {
        /// <summary>The pre-4.0 single-file layout. Never read for settings;
        /// used only by the both-layouts refusal.</summary>
        internal const string FileName = "ckf.hardmode.json";

        /// <summary>The slice directory, under BepInEx/config. Flat:
        /// Overlays.Load does not recurse and this does not either.</summary>
        internal const string DirName = "ckf.hardmode.d";

        // The nine settings subsystems. Each name plus ".json" is the file
        // named by targets.json in the matching schema/*.schema.json.
        internal const string ModelRules  = "modelrules";
        internal const string SelfCheck   = "selfcheck";
        internal const string PowerLevel  = "powerlevel";
        internal const string TeamPl      = "teampl";
        internal const string Fatigue     = "fatigue";
        internal const string Elapse      = "elapse";
        internal const string Missions    = "missions";
        internal const string RewardCurve = "rewardcurve";
        internal const string Difficulty  = "difficulty";

        /// <summary>The tenth settings file. Not a subsystem: it holds the
        /// three blanket implant multipliers (costMultiply,
        /// installTimeMultiply, implantStressMultiply), which
        /// Implants.ExpandGlobal applies to every ImplantModel row. This file
        /// is their only source. They are multiplies, and `multiply` is not
        /// idempotent, so they must never also arrive as a rule from another
        /// file.</summary>
        internal const string ImplantsGlobal = "implants-global";

        // In the order Plugin.Load initialises the subsystems, so the summary
        // line reads in the same order as the log below it.
        private static readonly string[] Sections =
            { ModelRules, SelfCheck, PowerLevel, TeamPl, Fatigue,
              Elapse, Missions, RewardCurve, Difficulty };

        // Every settings file this class owns: the nine, in that same order,
        // plus implants-global. Derived from Sections rather than retyped, so
        // the two cannot drift.
        private static readonly string[] Slots = BuildSlots();

        private static string[] BuildSlots()
        {
            var all = new string[Sections.Length + 1];
            Array.Copy(Sections, all, Sections.Length);
            all[Sections.Length] = ImplantsGlobal;
            return all;
        }

        // "_version" is the upgrade stamp; it belongs to no subsystem and is
        // never a stray.
        private const string VersionKey = "_version";

        // Slot -> the top-level keys that slot's file is allowed to carry.
        //
        // TRANSCRIBED, NOT DECLARED HERE. Each list is the `fields` array of the
        // matching schema/*.schema.json with `in` != "cfg", plus the retired
        // "enabled" gate Slices.ReportRetiredGate reports. Keep the two in step
        // by hand, as with Slices.OverlayOwner. implants-global also accepts
        // "_doc" and the retired "implantStressClampMin" (Implants.cs parses
        // and ignores it).
        //
        // "difficulty" has no "enabled": it never carried one, so one appearing
        // there is a stray and is reported as one.
        private static readonly Dictionary<string, string[]> Declared =
            new Dictionary<string, string[]>(StringComparer.Ordinal)
        {
            { ModelRules,  new[] { "enabled", "traceRules", "probeWritableColumns",
                                   "probeTables", "probeOutput" } },
            { SelfCheck,   new[] { "enabled", "file", "output" } },
            { PowerLevel,  new[] { "enabled", "minCap", "maxCap", "matrixMaxCap",
                                   "logFirst" } },
            { TeamPl,      new[] { "enabled", "table", "override" } },
            // runningEmpty and offDuty are the retired 4.0 stage blocks. They stay
            // DECLARED so a 4.0 file is reported as carrying a retired block
            // rather than a stray key; Fatigue.LegacyKeys names them and
            // Fatigue.Validate refuses the file, because their curves do not
            // stand behind the 4.1 ones.
            { Fatigue,     new[] { "enabled", "byPowerLevel", "knight",
                                   "tier1", "tier2", "tier3", "woundResist",
                                   "deterministicRolls", "logGrants",
                                   "runningEmpty", "offDuty" } },
            { Elapse,      new[] { "enabled", "logFirst", "tiers", "credits", "stress",
                                   "seedSalt" } },
            { Missions,    new[] { "enabled", "missions" } },
            { RewardCurve, new[] { "enabled", "logEffectiveCurve", "curve" } },
            { Difficulty,  new[] { "sliderRangeMultiplier" } },
            { ImplantsGlobal, new[] { "_doc", "costMultiply", "installTimeMultiply",
                                      "implantStressMultiply", "implantStressClampMin" } },
        };

        private enum State
        {
            Unread,       // Ensure() has not run yet
            Ok,           // parsed; Text is populated
            FileMissing,  // not on disk
            Unreadable,   // on disk, the read threw
            NotJson,      // read, would not parse
            NotObject     // parsed, root is not an object
        }

        private sealed class Slot
        {
            internal State State = State.Unread;
            internal string Path;        // full path, for messages
            internal string Problem;     // OS or JSON error text; null when Ok
            internal string Text;        // the file's whole JSON body, or null
            internal string Version;     // its "_version" stamp, or null
            internal int Strays;
        }

        private static readonly Dictionary<string, Slot> slots =
            new Dictionary<string, Slot>(StringComparer.Ordinal);

        private static bool ran;

        /// <summary>True when ckf.hardmode.json is on disk AND at least one
        /// slice file is. Plugin.Load applies nothing when this is set; see
        /// the header.</summary>
        internal static bool BothLayouts { get; private set; }

        /// <summary>The stamp on one slot's file, or null. Nothing fills a new
        /// key from it; see ReportStamps below.</summary>
        internal static string VersionOf(string section)
        {
            Ensure();
            Slot s;
            return slots.TryGetValue(section, out s) ? s.Version : null;
        }

        /// <summary>The file name one slot lives in: "elapse.json".</summary>
        internal static string FileFor(string section)
        {
            return section + ".json";
        }

        /// <summary>True when <paramref name="fileName"/> is one of the ten
        /// settings files this class reads. Overlays asks before it opens a
        /// file in ckf.hardmode.d, because a settings file deserialised as a
        /// RuleFile yields zero rules and NO ERROR, a silent instrument
        /// (AGENTS.md).</summary>
        internal static bool OwnsFile(string fileName)
        {
            if (fileName == null) return false;
            foreach (var s in Slots)
                if (string.Equals(fileName, FileFor(s), StringComparison.OrdinalIgnoreCase))
                    return true;
            return false;
        }

        /// <summary>True when that slot's file could not be read or parsed at
        /// all, as opposed to being read fine and simply not carrying what was
        /// asked for. Callers log the first at Error and the second at their own
        /// level. State is per file, so the answer is for the slot
        /// asked about.</summary>
        internal static bool CouldNotRead(string section)
        {
            Ensure();
            Slot s;
            if (!slots.TryGetValue(section, out s)) return false;
            return s.State != State.Ok;
        }

        /// <summary>Force the read and run the guards, so they fire and the
        /// summary line lands even on a launch where every subsystem is switched
        /// off and nothing would otherwise ask.</summary>
        internal static void Init()
        {
            Ensure();
        }

        /// <summary>The slot's JSON text, or null when its file could not be
        /// read. Callers pass the text straight to their own
        /// JsonSerializer.Deserialize.</summary>
        internal static string SectionText(string section)
        {
            Ensure();
            Slot s;
            return slots.TryGetValue(section, out s) ? s.Text : null;
        }

        /// <summary>Where a slot lives, for a message: its own file's
        /// path.</summary>
        internal static string Where(string section)
        {
            Ensure();
            Slot s;
            if (slots.TryGetValue(section, out s) && s.Path != null) return s.Path;
            return Path.Combine(Paths.ConfigPath, DirName, FileFor(section));
        }

        /// <summary>One clause saying why <paramref name="section"/> produced
        /// nothing, distinguishing "not there" from "could not look". Callers
        /// append their own consequence and finish the sentence. "Missing"
        /// means the slice's own file.</summary>
        internal static string WhyNo(string section)
        {
            Ensure();
            var path = Where(section);
            Slot s;
            var state = slots.TryGetValue(section, out s) ? s.State : State.FileMissing;
            var problem = s == null ? null : s.Problem;

            switch (state)
            {
                case State.FileMissing:
                    return $"{path} is missing, so this slice has nothing to read";
                case State.Unreadable:
                    return $"{path} could not be READ — {problem} — so it is not known "
                         + "what this slice is set to";
                case State.NotJson:
                    return $"{path} is not valid JSON ({problem}), so nothing could be read "
                         + "out of it";
                case State.NotObject:
                    return $"{path} parsed, but its root is not a JSON object, so it carries "
                         + "no settings at all";
                default:
                    return $"{path} has no \"{section}\" settings";
            }
        }

        // ---- reading one flat slot -------------------------------------------
        //
        // The four slots whose files are flat (modelrules, powerlevel,
        // selfcheck, difficulty) hold scalars and nothing else, so their
        // loader shape lives here once.
        //
        // The five nested loaders (teampl, fatigue, elapse, missions,
        // rewardcurve) are NOT routed through this. Each walks its own blocks
        // to name an unknown key.

        /// <summary>A POCO that can report the keys it did not recognise.
        /// Implement it by returning the [JsonExtensionData] bag.</summary>
        internal interface IHasUnknownKeys
        {
            Dictionary<string, JsonElement> UnknownKeys { get; }
        }

        /// <summary>Deserialise one flat slot, or return null having said why.
        /// Null means the caller does nothing at all this launch.
        ///
        /// <paramref name="consequence"/> is one sentence naming what the
        /// caller will not be doing; it is appended to the reason. The reason
        /// itself comes from <see cref="WhyNo"/>, so an unreadable file says the
        /// settings could not be read rather than implying someone set a toggle
        /// to false.
        ///
        /// <paramref name="absentIsOrdinary"/> drops an ABSENT file from Warning
        /// to Info, for the one subsystem whose switch defaults to off. It
        /// never touches the unreadable path: that stays an Error whatever the
        /// caller thinks of an absence, because "not there" and "could not look"
        /// are different findings (AGENTS.md).</summary>
        internal static T ReadSection<T>(string subsystem, string section, string consequence,
                                         bool absentIsOrdinary = false)
            where T : class, IHasUnknownKeys
        {
            var where = Where(section);
            var text = SectionText(section);
            if (text == null)
            {
                var why = $"{subsystem}: {WhyNo(section)}. {consequence}";
                if (CouldNotRead(section)) Plugin.Log.LogError(why);
                else if (absentIsOrdinary) Plugin.Log.LogInfo(why);
                else Plugin.Log.LogWarning(why);
                return null;
            }

            T parsed;
            try
            {
                // The same two options every loader in this assembly parses
                // with. PropertyNameCaseInsensitive is deliberately NOT set:
                // a miscased key has to land in the extension-data bag and be
                // reported, not be silently accepted.
                var opts = new JsonSerializerOptions
                {
                    ReadCommentHandling = JsonCommentHandling.Skip,
                    AllowTrailingCommas = true
                };
                parsed = JsonSerializer.Deserialize<T>(text, opts);
            }
            catch (JsonException e)
            {
                Plugin.Log.LogError($"{subsystem}: {where} is not valid JSON: {e.Message}"
                    + (string.IsNullOrEmpty(e.Path) ? "" : $" (at {e.Path})")
                    + $" {consequence}");
                return null;
            }
            catch (Exception e)
            {
                Plugin.Log.LogError($"{subsystem}: could not read {where}: "
                    + $"{e.GetType().Name}: {e.Message}. {consequence}");
                return null;
            }

            if (parsed == null)
            {
                Plugin.Log.LogError($"{subsystem}: {where} parsed to nothing. {consequence}");
                return null;
            }

            // Same rule as the five nested loaders: an unrecognised key is
            // refused rather than ignored, because ignoring it means the player
            // set something and nothing happened, with nothing in the log.
            //
            // "_version" is the stamp and belongs to no POCO, so it would land
            // in every extension-data bag and refuse every file. It is dropped
            // from the bag here rather than added as a property to four POCOs.
            var unknown = parsed.UnknownKeys;
            if (unknown != null) unknown.Remove(VersionKey);
            if (unknown != null && unknown.Count > 0)
            {
                foreach (var key in unknown.Keys)
                    Plugin.Log.LogError($"{subsystem}: {where}: \"{key}\" is not a key this "
                        + "file has.");
                Plugin.Log.LogError($"{subsystem}: {unknown.Count} unrecognised key(s) in "
                    + $"{where}. Key names are case-sensitive and have to be spelled exactly "
                    + $"as in the file shipped with the mod. {consequence}");
                return null;
            }

            return parsed;
        }

        // ---- the read --------------------------------------------------------

        private static void Ensure()
        {
            if (ran) return;
            ran = true;

            var dir = Path.Combine(Paths.ConfigPath, DirName);
            var legacy = Path.Combine(Paths.ConfigPath, FileName);

            foreach (var name in Slots)
                slots[name] = new Slot { Path = Path.Combine(dir, FileFor(name)) };

            foreach (var name in Slots)
                ReadOne(name, slots[name]);

            // ---- the both-layouts refusal ------------------------------------
            //
            // Presence only: the old file on disk at the same time as any
            // slice file. Not "carries a section": narrowing it to that would
            // be this class deciding which of two copies of the player's
            // tuning is the real one, which is what the refusal exists to
            // refuse.
            var anySlice = 0;
            foreach (var name in Slots)
                if (slots[name].State != State.FileMissing) anySlice++;

            var legacyThere = false;
            try { legacyThere = File.Exists(legacy); }
            catch (Exception e)
            {
                // Could not look. NOT "it is not there" (AGENTS.md).
                // Treated as present, because refusing costs a launch and
                // applying a half-migrated config costs the tuning.
                legacyThere = true;
                Plugin.Log.LogError("ConfigDoc: could not tell whether " + legacy
                    + " exists: " + e.GetType().Name + ": " + e.Message + ". That is NOT the "
                    + "same as it being absent, so it is treated as PRESENT: if any slice "
                    + "file is on disk, the mod applies nothing this launch. Fix the error "
                    + "and relaunch.");
            }

            if (legacyThere && anySlice > 0)
            {
                BothLayouts = true;
                Plugin.Log.LogError("ConfigDoc: BOTH CONFIG LAYOUTS ARE ON DISK. "
                    + legacy + " is the settings file from before 4.0, and " + dir
                    + " holds " + anySlice + " settings file(s) from 4.0 or later. "
                    + "The game runs unmodified this launch: with two copies of the "
                    + "settings present, the mod will not guess which one counts. "
                    + "Delete " + legacy + " and relaunch (see the README, \"Updating "
                    + "from an earlier version\"). Nothing on disk was changed.");
            }

            ReportStamps();
            ReportSummary(dir, anySlice);
        }

        private static void ReadOne(string name, Slot slot)
        {
            string text;
            try
            {
                if (!File.Exists(slot.Path))
                {
                    slot.State = State.FileMissing;
                    return;     // named on the summary line below, not one Warning each
                }
                text = File.ReadAllText(slot.Path);
            }
            catch (Exception e)
            {
                // Denied, locked, or a bad sector. NOT the same finding as
                // "missing" — this one means the answer is unknown.
                slot.State = State.Unreadable;
                slot.Problem = $"{e.GetType().Name}: {e.Message}";
                Plugin.Log.LogError($"ConfigDoc: could not read {slot.Path}: {slot.Problem}. "
                    + "This is not the same as the file being absent — the file is there and "
                    + "its contents are unknown. The subsystem that reads it does nothing this "
                    + "launch, for want of settings rather than for want of a switch: the "
                    + "switches are in ckf.hardmode.cfg and were read before this.");
                return;
            }

            try
            {
                var opts = new JsonDocumentOptions
                {
                    CommentHandling = JsonCommentHandling.Skip,
                    AllowTrailingCommas = true
                };
                using (var doc = JsonDocument.Parse(text, opts))
                {
                    var root = doc.RootElement;
                    if (root.ValueKind != JsonValueKind.Object)
                    {
                        slot.State = State.NotObject;
                        Plugin.Log.LogError($"ConfigDoc: {slot.Path} is valid JSON but its root "
                            + $"is a {root.ValueKind}, not an object. A slice file is "
                            + "{ \"_version\": ..., ...that slice's keys... }. The subsystem "
                            + "that reads it does nothing this launch; the switches in "
                            + "ckf.hardmode.cfg are unaffected.");
                        return;
                    }

                    string[] declared;
                    if (!Declared.TryGetValue(name, out declared)) declared = new string[0];
                    var known = new HashSet<string>(declared, StringComparer.Ordinal);

                    var seen = new HashSet<string>(StringComparer.Ordinal);
                    var strays = new List<string>();

                    foreach (var prop in root.EnumerateObject())
                    {
                        var key = prop.Name;

                        // A duplicate top-level key is last-wins in the parse
                        // and invisible everywhere else, so it gets said out
                        // loud rather than silently discarded.
                        if (!seen.Add(key))
                            Plugin.Log.LogError($"ConfigDoc: {slot.Path} has more than one "
                                + $"top-level \"{key}\" key. The LAST one wins and the earlier "
                                + "one is discarded — whichever you edited, only one of them is "
                                + "being read. Delete the duplicate.");

                        if (key == VersionKey)
                        {
                            slot.Version = prop.Value.ValueKind == JsonValueKind.String
                                         ? prop.Value.GetString()
                                         : prop.Value.GetRawText();
                            continue;
                        }

                        if (!known.Contains(key)) strays.Add(key);
                    }

                    // THE GUARD, PER FILE. A key this slice does not declare is
                    // read by nothing, so without this it would cost the player
                    // their edit in silence on a launch where the subsystem is
                    // switched off and its own loader never runs. The text is
                    // still served: the loader's extension-data bag reports the
                    // same key with its own wording and refuses the file, which
                    // is the behaviour a player sees either way.
                    slot.Strays = strays.Count;
                    foreach (var stray in strays)
                        Plugin.Log.LogError($"ConfigDoc: {slot.Path}: top-level key \"{stray}\" "
                            + "is not a key this slice has and NOTHING READS IT. Key names are "
                            + "case-sensitive; this file's are \""
                            + string.Join("\", \"", declared)
                            + "\", plus \"" + VersionKey + "\". If that is a misspelling of one "
                            + "of them, your setting is being ignored.");

                    // WHAT THE LOADERS GET, AND WHY "_version" IS NOT IN IT.
                    //
                    // Elapse.Options and Fatigue's root block each carry a
                    // [JsonExtensionData] bag and REFUSE THE WHOLE FILE on any
                    // key that maps to no member (Elapse.Load returns null and
                    // the feature is off for the launch). The stamp maps to no
                    // member in any of them, so serving the raw object would
                    // switch Elapse and Fatigue OFF on every launch.
                    //
                    // So the served text is the object minus "_version" and
                    // nothing else, and no POCO gains a stamp property it has
                    // no use for. The four flat
                    // loaders that route through ReadSection are covered twice
                    // over — it drops the key from the bag as well — because
                    // that path is also reachable from a test harness that
                    // builds its own text.
                    using (var buf = new MemoryStream())
                    {
                        using (var w = new Utf8JsonWriter(buf))
                        {
                            w.WriteStartObject();
                            foreach (var prop in root.EnumerateObject())
                                if (prop.Name != VersionKey) prop.WriteTo(w);
                            w.WriteEndObject();
                        }
                        slot.Text = Encoding.UTF8.GetString(buf.ToArray());
                    }
                    slot.State = State.Ok;
                }
            }
            catch (JsonException e)
            {
                // A missing brace or a bad number costs THIS slice its settings
                // and no other. That is the whole point of the split.
                slot.State = State.NotJson;
                slot.Text = null;
                slot.Problem = e.Message + (string.IsNullOrEmpty(e.Path) ? "" : $" (at {e.Path})");
                Plugin.Log.LogError($"ConfigDoc: {slot.Path} is not valid JSON: {slot.Problem}. "
                    + "The subsystem that reads this file does nothing this launch rather than "
                    + "running on built-in defaults. One syntax error costs one slice its "
                    + "settings and no other slice anything; it never costs a switch, because "
                    + "the switches are in ckf.hardmode.cfg and were read before this.");
            }
            catch (Exception e)
            {
                // Never throw past a loader. A broken file turns one feature
                // off; it does not take the plugin with it.
                slot.State = State.NotJson;
                slot.Text = null;
                slot.Problem = $"{e.GetType().Name}: {e.Message}";
                Plugin.Log.LogError($"ConfigDoc: could not parse {slot.Path}: {slot.Problem}. "
                    + "The subsystem that reads it does nothing this launch; the switches in "
                    + "ckf.hardmode.cfg are unaffected.");
            }
        }

        // ---- the stamps -------------------------------------------------------
        //
        // THIS INSTRUMENT REPORTS THAT IT DID NOT ACT (AGENTS.md).
        //
        // The assembly carries no embedded defaults (see Defaults.cs), so there
        // is nothing to fill a missing key FROM, and a silent pass would read as
        // "checked, nothing to do". Instead this reads every stamp, compares it
        // to Defaults.DocVersion, and says which files differ and that NOTHING
        // WAS FILLED IN. The upgrade path is extracting the release zip.
        private static void ReportStamps()
        {
            var missing = new List<string>();
            var behind = new List<string>();
            int matched = 0, unread = 0;

            foreach (var name in Slots)
            {
                var s = slots[name];
                if (s.State != State.Ok) { unread++; continue; }
                if (s.Version == null) missing.Add(FileFor(name));
                else if (s.Version == Defaults.DocVersion) matched++;
                else behind.Add(FileFor(name) + " (" + s.Version + ")");
            }

            var line = "ConfigDoc: _version stamps — " + matched + " at "
                     + Defaults.DocVersion + ", " + behind.Count + " at another version, "
                     + missing.Count + " unstamped, " + unread + " not read."
                     + (behind.Count == 0 ? "" : " Other version: "
                        + string.Join(", ", behind) + ".")
                     + (missing.Count == 0 ? "" : " Unstamped: "
                        + string.Join(", ", missing) + ".");

            if (behind.Count > 0 || missing.Count > 0)
            {
                Plugin.Log.LogWarning(line);
                Plugin.Log.LogWarning("ConfigDoc: NO KEY WAS FILLED IN AND NO FILE WAS "
                    + "REWRITTEN. This assembly carries no embedded defaults to fill from — "
                    + "see Defaults.cs — so an out-of-date slice file keeps exactly the keys it "
                    + "has, and any key a newer version added is simply absent and takes that "
                    + "subsystem's built-in default. To pick up new keys, extract the release "
                    + "zip's BepInEx\\config over your game folder, keeping a copy of anything "
                    + "you have retuned.");
            }
            else
            {
                Plugin.Log.LogInfo(line);
            }
        }

        private static void ReportSummary(string dir, int found)
        {
            var missing = new List<string>();
            var broken = new List<string>();
            int strays = 0;

            foreach (var name in Slots)
            {
                var s = slots[name];
                if (s.State == State.FileMissing) missing.Add(FileFor(name));
                else if (s.State != State.Ok) broken.Add(FileFor(name));
                strays += s.Strays;
            }

            var line = "ConfigDoc: " + dir + " — " + found + " of " + Slots.Length
                     + " slice file(s) found"
                     + (missing.Count == 0 ? "" : ", missing: " + string.Join(", ", missing))
                     + (broken.Count == 0 ? "" : ", unusable: " + string.Join(", ", broken))
                     + (strays == 0 ? "" : ", " + strays + " unrecognised key(s) — see above")
                     + ".";

            if (missing.Count > 0 || broken.Count > 0 || strays > 0) Plugin.Log.LogError(line);
            else Plugin.Log.LogInfo(line);

            // implants-global.json is read and guarded here but applied by
            // Implants.ExpandGlobal, so this line says where its numbers go.
            var ig = slots[ImplantsGlobal];
            if (ig.State == State.Ok)
                Plugin.Log.LogInfo("ConfigDoc: " + FileFor(ImplantsGlobal) + " was read and "
                    + "guarded. It is the only source of the three blanket implant "
                    + "multipliers: Implants.ExpandGlobal applies them to every ImplantModel "
                    + "row with no selector, including the drone modules in slots 100-107 "
                    + "that no table shows (accepted, not a bug). See the Implants: lines "
                    + "below for the numbers.");
        }
    }
}
