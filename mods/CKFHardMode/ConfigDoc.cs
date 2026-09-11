// ConfigDoc — the one merged config document, read once.
//
// 3.0 replaced the five sidecars (ckf.hardmode.elapse.json and friends) with
// one BepInEx/config/ckf.hardmode.json namespaced by section, and then took
// 21 of the 22 keys out of ckf.hardmode.cfg and put them in it too:
//
//     { "_version": "3.0.0",
//       "modelrules": {...}, "selfcheck": {...}, "powerlevel": {...},
//       "teampl": {...}, "fatigue": {...}, "elapse": {...},
//       "missions": {...}, "rewardcurve": {...}, "difficulty": {...} }
//
// Nine sections. Five came from a 2.x sidecar; the other four are new and
// their keys came out of the .cfg, which is why their schemas carry
// "legacyJson": null. [General] Enabled is the one key that stays a BepInEx
// bind: it is the switch that has to work when this document does not exist.
//
// Nothing INSIDE a section moved, which is why no POCO, no [JsonPropertyName]
// and no field path in schema/*.schema.json had to change. Each loader still
// deserialises its own whole object; this only swaps where the text comes
// from. `SectionText` hands back the section's raw JSON slice, so the loader's
// own JsonSerializer call, its [JsonExtensionData] bags, its defaulting and
// every one of its error paths are untouched.
//
// THE GUARD THIS FILE EXISTS FOR
//
// Splitting the config gave one check away free. A stray key at a sidecar's
// root landed in that POCO's [JsonExtensionData] bag, and the loader refused
// the file — loudly, by name. In a merged document a MISSPELLED SECTION
// ("elapes") belongs to no POCO at all: no deserialiser ever sees it, and the
// subsystem runs on defaults with nothing in the log. That is a loud failure
// turned silent, which is exactly what AGENTS.md §3 forbids.
//
// So every top-level key is checked here against the known section names plus
// "_version", and a stray is an Error naming the key. scripts/merge_sidecars.py
// --check and schema/check_schema.py report the same key offline; this is the
// runtime half of the same guard.
//
// AGENTS.md §3 also applies to the read itself: "the section is not there" and
// "the document could not be read" are different findings and get different
// sentences. `WhyNo` is what says which, and `CouldNotRead` is what decides
// whether the caller logs it at Warning or Error.

using System;
using System.Collections.Generic;
using System.IO;
using System.Text.Json;
using BepInEx;

namespace CKFHardMode
{
    internal static class ConfigDoc
    {
        internal const string FileName = "ckf.hardmode.json";

        // The nine sections. Must match targets.section across
        // schema/*.schema.json — schema/check_schema.py is what checks that
        // they still agree, and a section declared in one and not the other
        // becomes a stray the guard below reports.
        internal const string ModelRules  = "modelrules";
        internal const string SelfCheck   = "selfcheck";
        internal const string PowerLevel  = "powerlevel";
        internal const string TeamPl      = "teampl";
        internal const string Fatigue     = "fatigue";
        internal const string Elapse      = "elapse";
        internal const string Missions    = "missions";
        internal const string RewardCurve = "rewardcurve";
        internal const string Difficulty  = "difficulty";

        // In the order Plugin.Load initialises the subsystems, so the summary
        // line reads in the same order as the log below it.
        private static readonly string[] Sections =
            { ModelRules, SelfCheck, PowerLevel, TeamPl, Fatigue,
              Elapse, Missions, RewardCurve, Difficulty };

        // Everything a top-level key is allowed to be. "_version" is the
        // upgrade stamp; it belongs to no subsystem and is not a stray.
        private const string VersionKey = "_version";

        private enum State
        {
            Unread,       // Ensure() has not run yet
            Ok,           // parsed; Raw is populated
            FileMissing,  // not on disk
            Unreadable,   // on disk, the read threw
            NotJson,      // read, would not parse
            NotObject     // parsed, root is not an object
        }

        private static State state = State.Unread;

        // section name -> that section's raw JSON text. Populated for the
        // sections the document actually carries, which is not necessarily all
        // nine. The JsonDocument is parsed, sliced and disposed inside Ensure:
        // GetRawText copies, so these strings outlive it.
        private static readonly Dictionary<string, string> Raw =
            new Dictionary<string, string>(StringComparer.Ordinal);

        private static string path;      // full path, for messages
        private static string problem;   // OS or JSON error text; null when Ok

        /// <summary>The document's "_version" stamp, or null. Phase 4's upgrade
        /// pass is what acts on it; nothing reads it yet.</summary>
        internal static string Version { get; private set; }

        /// <summary>True when the document could not be read or parsed at all,
        /// as opposed to being read fine and simply not carrying a section.
        /// Callers log the first at Error and the second at their own level.
        /// </summary>
        internal static bool CouldNotRead
        {
            get
            {
                Ensure();
                return state != State.Ok;
            }
        }

        /// <summary>Force the read and run the stray-key guard, so the guard
        /// fires and the summary line lands even on a launch where every
        /// subsystem is switched off and nothing would otherwise ask.</summary>
        internal static void Init()
        {
            Ensure();
        }

        /// <summary>The section's raw JSON text, or null when the document
        /// could not be read or does not carry that section. Callers pass the
        /// text straight to their own JsonSerializer.Deserialize.</summary>
        internal static string SectionText(string section)
        {
            Ensure();
            string text;
            return Raw.TryGetValue(section, out text) ? text : null;
        }

        /// <summary>Where a section lives, for a message: the file path plus
        /// the section name. Replaces the sidecar path the loaders used to
        /// interpolate.</summary>
        internal static string Where(string section)
        {
            Ensure();
            return $"{path} section \"{section}\"";
        }

        /// <summary>One clause saying why <paramref name="section"/> produced
        /// nothing, distinguishing "not there" from "could not look". Callers
        /// append their own consequence and finish the sentence.</summary>
        internal static string WhyNo(string section)
        {
            Ensure();
            switch (state)
            {
                case State.FileMissing:
                    return $"{path} is missing, so no section could be read";
                case State.Unreadable:
                    return $"{path} could not be READ — {problem} — so it is not known "
                         + $"whether it has a \"{section}\" section";
                case State.NotJson:
                    return $"{path} is not valid JSON ({problem}), so no section could be "
                         + "read out of it";
                case State.NotObject:
                    return $"{path} parsed, but its root is not a JSON object, so it has no "
                         + "sections at all";
                default:
                    return $"{path} has no \"{section}\" section";
            }
        }

        // ---- reading one flat section ---------------------------------------
        //
        // The four sections Phase 3 created — modelrules, powerlevel, selfcheck
        // and difficulty — are flat: scalars and nothing else. Their loaders
        // would otherwise be four copies of the same forty lines the five
        // sidecar loaders already carry by hand, so the shape lives here once.
        //
        // The five older loaders are NOT routed through this. Their sections
        // are nested and each walks its own blocks to name an unknown key, and
        // rewriting them to fit would be a change to code Run58 confirmed for
        // no gain.

        /// <summary>A section POCO that can report the keys it did not
        /// recognise. Implement it by returning the [JsonExtensionData]
        /// bag.</summary>
        internal interface IHasUnknownKeys
        {
            Dictionary<string, JsonElement> UnknownKeys { get; }
        }

        /// <summary>Deserialise one flat section, or return null having said
        /// why. Null means the caller does nothing at all this launch.
        ///
        /// <paramref name="consequence"/> is one sentence naming what the
        /// caller will not be doing; it is appended to the reason. The reason
        /// itself comes from <see cref="WhyNo"/>, so an unreadable document
        /// says the settings could not be read rather than implying someone
        /// set a toggle to false.
        ///
        /// <paramref name="absentIsOrdinary"/> drops an ABSENT section from
        /// Warning to Info, for the one subsystem whose shipped state is off
        /// anyway. It never touches the unreadable-document path: that stays an
        /// Error whatever the caller thinks of an absence, because "not there"
        /// and "could not look" are different findings (AGENTS.md §3).</summary>
        internal static T ReadSection<T>(string subsystem, string section, string consequence,
                                         bool absentIsOrdinary = false)
            where T : class, IHasUnknownKeys
        {
            var where = Where(section);
            var text = SectionText(section);
            if (text == null)
            {
                var why = $"{subsystem}: {WhyNo(section)}. {consequence}";
                if (CouldNotRead) Plugin.Log.LogError(why);
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

            // Same rule as the five sidecar loaders: an unrecognised key is
            // refused rather than ignored, because ignoring it means the player
            // set something and nothing happened, with nothing in the log.
            var unknown = parsed.UnknownKeys;
            if (unknown != null && unknown.Count > 0)
            {
                foreach (var key in unknown.Keys)
                    Plugin.Log.LogError($"{subsystem}: {where}: \"{key}\" is not a key this "
                        + "section has.");
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
            if (state != State.Unread) return;

            path = Path.Combine(Paths.ConfigPath, FileName);

            string text;
            try
            {
                if (!File.Exists(path))
                {
                    state = State.FileMissing;
                    Plugin.Log.LogWarning($"ConfigDoc: {path} is not on disk. Since 3.0 that is "
                        + "every setting the mod has except [General] Enabled, so every "
                        + "subsystem says so for itself below and does nothing.");
                    return;
                }
                text = File.ReadAllText(path);
            }
            catch (Exception e)
            {
                // Denied, locked, or a bad sector. NOT the same finding as
                // "missing" — this one means the answer is unknown.
                state = State.Unreadable;
                problem = $"{e.GetType().Name}: {e.Message}";
                Plugin.Log.LogError($"ConfigDoc: could not read {path}: {problem}. This is not "
                    + "the same as the file being absent — the file is there and its contents "
                    + "are unknown. Every subsystem except the master switch is OFF this "
                    + "launch.");
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
                        state = State.NotObject;
                        Plugin.Log.LogError($"ConfigDoc: {path} is valid JSON but its root is a "
                            + $"{root.ValueKind}, not an object. The document is "
                            + "{ \"_version\": ..., \"elapse\": {...}, ... }. Every subsystem "
                            + "except the master switch is OFF this launch.");
                        return;
                    }

                    var known = new HashSet<string>(Sections, StringComparer.Ordinal);
                    var seen = new HashSet<string>(StringComparer.Ordinal);
                    var strays = new List<string>();

                    foreach (var prop in root.EnumerateObject())
                    {
                        var name = prop.Name;

                        // A duplicate top-level key is last-wins in the parse
                        // and invisible everywhere else, so it gets said out
                        // loud rather than silently discarded.
                        if (!seen.Add(name))
                            Plugin.Log.LogError($"ConfigDoc: {path} has more than one top-level "
                                + $"\"{name}\" key. The LAST one wins and the earlier one is "
                                + "discarded — whichever you edited, only one of them is being "
                                + "read. Delete the duplicate.");

                        if (name == VersionKey)
                        {
                            Version = prop.Value.ValueKind == JsonValueKind.String
                                    ? prop.Value.GetString()
                                    : prop.Value.GetRawText();
                            continue;
                        }

                        if (known.Contains(name))
                        {
                            // GetRawText copies the slice, so it survives the
                            // JsonDocument being disposed below. Comments and
                            // trailing commas inside the section come through
                            // in the raw text; every loader parses with the
                            // same two options, so they still parse.
                            Raw[name] = prop.Value.GetRawText();
                            continue;
                        }

                        strays.Add(name);
                    }

                    state = State.Ok;

                    // THE GUARD. A section name that belongs to no subsystem is
                    // read by nothing, so without this it would cost the player
                    // their whole edit in silence. See the header.
                    foreach (var stray in strays)
                        Plugin.Log.LogError($"ConfigDoc: {path}: top-level key \"{stray}\" is not "
                            + "a section this mod knows and NOTHING READS IT. Section names are "
                            + "case-sensitive; the " + Sections.Length + " are \""
                            + string.Join("\", \"", Sections)
                            + "\", plus \"" + VersionKey + "\". If that is a misspelling of one "
                            + "of them, the subsystem it was meant for is running on its "
                            + "built-in defaults and your settings in that block are being "
                            + "ignored.");

                    var present = new List<string>();
                    foreach (var s in Sections)
                        if (Raw.ContainsKey(s)) present.Add(s);

                    var names = present.Count == 0 ? "none" : string.Join(", ", present);
                    var stamp = Version == null ? "no " + VersionKey : VersionKey + " " + Version;
                    var tail = strays.Count == 0
                             ? "."
                             : $", and {strays.Count} unrecognised top-level key(s) — see above.";
                    var summary = $"ConfigDoc: {path} — {present.Count} of {Sections.Length} "
                                + $"section(s) present ({names}), {stamp}{tail}";

                    if (strays.Count > 0) Plugin.Log.LogError(summary);
                    else Plugin.Log.LogInfo(summary);
                }
            }
            catch (JsonException e)
            {
                // A missing brace or a bad number anywhere in the document
                // takes all nine sections with it, which is the one thing the
                // merge genuinely costs. e.Path locates it when it has one.
                state = State.NotJson;
                Raw.Clear();      // never serve half a document
                problem = e.Message + (string.IsNullOrEmpty(e.Path) ? "" : $" (at {e.Path})");
                Plugin.Log.LogError($"ConfigDoc: {path} is not valid JSON: {problem}. ALL "
                    + Sections.Length + " sections are unreadable, so every subsystem except "
                    + "the master switch is OFF this launch rather than running on built-in "
                    + "defaults. One syntax error anywhere in this document costs all of them; "
                    + "that is what the merge costs and it is stated here rather than left for "
                    + "you to work out.");
            }
            catch (Exception e)
            {
                // Never throw past a loader. A broken document turns features
                // off; it does not take the plugin with it.
                state = State.NotJson;
                Raw.Clear();      // never serve half a document
                problem = $"{e.GetType().Name}: {e.Message}";
                Plugin.Log.LogError($"ConfigDoc: could not parse {path}: {problem}. Every "
                    + "subsystem except the master switch is OFF this launch.");
            }
        }
    }
}
