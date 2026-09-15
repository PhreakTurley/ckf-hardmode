// ConfigDoc — one settings file per slice, read once.
//
// 3.0 replaced the five sidecars (ckf.hardmode.elapse.json and friends) with
// one BepInEx/config/ckf.hardmode.json namespaced by section. Phase 3 of
// split-config-into-toggleable-slices takes that back apart, for the reason
// design.md section 1 gives: no slice's settings may live in a file another
// slice can disable, and one syntax error in a merged document costs all nine
// subsystems their settings at once.
//
// The layout this class now reads:
//
//     BepInEx/config/ckf.hardmode.d/
//       difficulty.json   elapse.json    fatigue.json
//       missions.json     rewardcurve.json  teampl.json
//       powerlevel.json   modelrules.json   selfcheck.json
//       implants-global.json
//
// Each file is { "_version": "4.0.0", ...that slice's keys... }. Nothing INSIDE
// a slice moved: the nine files' bodies are the nine sections of the old
// document, key for key and character for character, so no POCO, no
// [JsonPropertyName] and no field path in schema/*.schema.json changed. Each
// loader still deserialises its own whole object; this only swaps where the
// text comes from. `SectionText` keeps its signature and hands back the file's
// whole JSON body minus nothing, so the loader's own JsonSerializer call, its
// [JsonExtensionData] bags, its defaulting and every one of its error paths are
// untouched.
//
// CORRECTION, 2026-09-13 (Phase 3). This header used to say "the one merged
// config document, read once" and described ckf.hardmode.json as where every
// setting lives. That file is now the PRE-4.0 layout. `FileName` still names it,
// because two things still have to name it: the both-layouts refusal below, and
// the message Slices.ReportRetiredGate prints about a retired "enabled" key.
// It is no longer read for settings.
//
// CORRECTION, 2026-09-13 (Phase 3). tasks.md Phase 3 says of the stray-key
// guard: "Today every top-level key is checked against the five section names
// plus `_version`." It was checked against NINE section names plus "_version" —
// the `Sections` array below has had nine entries since 3.0 and check_schema.py
// declares nine `targets.section` values [measured, schema/*.schema.json,
// 2026-09-13]. The "five" is the count of the 2.x sidecars, which is a different
// number about a different thing. The instruction the sentence carries is
// unaffected and is implemented as written.
//
// THE GUARD THIS FILE EXISTS FOR, IN ITS NEW FORM
//
// A stray key at a sidecar's root lands in that POCO's [JsonExtensionData] bag
// and the loader refuses the file — loudly, by name. In a merged document a
// MISSPELLED SECTION ("elapes") belonged to no POCO at all: no deserialiser ever
// saw it, and the subsystem ran on defaults with nothing in the log. That is
// what the old guard caught.
//
// Per file, the same failure has two shapes and this class catches both:
//
//   1. A stray KEY inside a slice file. Checked here against that slice's own
//      declared keys — transcribed below from each schema's `fields`, plus the
//      retired "enabled" gate — and reported at Error by name. The file's text
//      is STILL SERVED, so the loader's own extension-data bag reports it too
//      with its own wording and refuses the file exactly as it does today. The
//      point of checking here as well is that this runs on a launch where the
//      subsystem is switched off and its loader never asks (AGENTS.md section
//      3: a guard that only runs when someone asks is one that can go quiet).
//
//   2. A misspelled FILE. There is no POCO and no loader for elapes.json, so
//      the summary line below names every expected slice file that is not on
//      disk, every launch, found-of-expected. Overlays names it from the other
//      side, on its "claimed by no slice" line.
//
// A DUPLICATE TOP-LEVEL KEY IS AN ERROR, not a shrug. JSON last-wins discards
// the earlier one, so a player who edited the first of two "curve" keys has
// edited nothing and has nothing in the log saying so.
//
// BOTH LAYOUTS PRESENT IS A REFUSAL. If ckf.hardmode.json is still on disk and
// any slice file is too, this class sets `BothLayouts` and Plugin.Load applies
// NO RULE this launch. A silent preference for one of the two would mean a
// player's tuning quietly stops applying — the half-applied state design.md
// section 3 exists to make unreachable. specs/config-surface/spec.md,
// "Both layouts present is a refusal, not a preference".
//
// AGENTS.md section 3 applies to the read itself: "the file is not there" and
// "the file could not be read" are different findings and get different
// sentences. `WhyNo` is what says which, and `CouldNotRead(section)` is what
// decides whether the caller logs it at Warning or Error. That method GAINED
// ITS PARAMETER in Phase 3 — state is per file now, and a parameterless answer
// would have reported one slice's unreadable file as another slice's.

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
        /// <summary>The PRE-4.0 merged document. Not read for settings any
        /// more; named by the both-layouts refusal and by
        /// Slices.ReportRetiredGate.</summary>
        internal const string FileName = "ckf.hardmode.json";

        /// <summary>The slice directory, under BepInEx/config. Flat:
        /// Overlays.Load does not recurse and this does not either.</summary>
        internal const string DirName = "ckf.hardmode.d";

        // The nine subsystem slices. Must match targets.section across
        // schema/*.schema.json — schema/check_schema.py is what checks that
        // they still agree.
        internal const string ModelRules  = "modelrules";
        internal const string SelfCheck   = "selfcheck";
        internal const string PowerLevel  = "powerlevel";
        internal const string TeamPl      = "teampl";
        internal const string Fatigue     = "fatigue";
        internal const string Elapse      = "elapse";
        internal const string Missions    = "missions";
        internal const string RewardCurve = "rewardcurve";
        internal const string Difficulty  = "difficulty";

        /// <summary>The tenth settings file. Not a subsystem section: it is the
        /// blanket implant multipliers (design.md section 7).
        ///
        /// CORRECTION, Phase 7. This comment said "four blanket implant
        /// multipliers" and "the expander arrives in Phase 7". Both moved.
        /// There are THREE numbers, not four: costMultiply, installTimeMultiply
        /// and implantStressMultiply. The fourth was implantStressClampMin, and
        /// David removed it because it provably never binds — ImplantStress is
        /// 1 on 197 rows (1 -> 3) and 5 on Quantum Rider (5 -> 15), so nothing
        /// lands below the floor for it to lift [measured, sheets\raw
        /// 2026-09-12]. Phase 9's migrator must not carry it back in.
        ///
        /// And the expander DID arrive in Phase 7 — mods/CKFHardMode/Implants.cs
        /// — but it deliberately emitted NOTHING from this file.
        ///
        /// RESOLVED IN PHASE 9, 2026-09-14. The paragraph above used to end
        /// "NOTHING READS ITS VALUES YET remains true; the reason changed." It
        /// is false now and is kept because the reason it was true is the whole
        /// hazard: the source rule is a MULTIPLY, `set` is idempotent and
        /// `multiply` is not, so with BOTH live the three numbers would have
        /// squared to x0.25, x0.25 and x9 across all 198 rows. Phase 9 deleted
        /// the unscoped ImplantModel rule and replaced Implants.RefuseGlobal
        /// with Implants.ExpandGlobal IN ONE COMMIT, because either half alone
        /// is a balance change. THIS FILE IS NOW THE ONLY SOURCE of x0.5, x0.5
        /// and x3, and 594 cells (198 rows x 3 columns) were measured equal
        /// across the swap [measured, 2026-09-14].
        /// </summary>
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
        // matching schema/*.schema.json with `in` != "cfg", plus "enabled" where
        // the file still carries the retired gate Slices.ReportRetiredGate
        // reports. schema/ is not this phase's directory to edit, so this is a
        // copy of a declaration rather than a second declaration — the same
        // arrangement as Slices.OverlayOwner. [measured, schema/*.schema.json
        // and the live ckf.hardmode.json, 2026-09-13]
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
            { Fatigue,     new[] { "enabled", "runningEmpty", "offDuty", "woundResist",
                                   "deterministicRolls", "logGrants" } },
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

        /// <summary>True when ckf.hardmode.json is still on disk AND at least
        /// one slice file is. Plugin.Load applies no rule when this is set; see
        /// the header and specs/config-surface/spec.md.</summary>
        internal static bool BothLayouts { get; private set; }

        /// <summary>The stamp on one slot's file, or null. Nothing fills a new
        /// key from it yet — see ReportStamps below, which says so rather than
        /// leaving the absence to be read as "nothing to do".</summary>
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
        /// RuleFile yields zero rules and NO ERROR — the silent-instrument
        /// shape AGENTS.md section 3 forbids.</summary>
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
        /// level.
        ///
        /// GAINED ITS PARAMETER IN PHASE 3. It used to be a parameterless
        /// property over one shared document. State is per file now, and an
        /// answer that ignored which file was asked about would report one
        /// slice's unreadable file as another slice's.</summary>
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
        /// JsonSerializer.Deserialize.
        ///
        /// SIGNATURE UNCHANGED. The five older loaders do not move.</summary>
        internal static string SectionText(string section)
        {
            Ensure();
            Slot s;
            return slots.TryGetValue(section, out s) ? s.Text : null;
        }

        /// <summary>Where a slot lives, for a message: its own file's path.
        /// Replaces "the document, section X".</summary>
        internal static string Where(string section)
        {
            Ensure();
            Slot s;
            if (slots.TryGetValue(section, out s) && s.Path != null) return s.Path;
            return Path.Combine(Paths.ConfigPath, DirName, FileFor(section));
        }

        /// <summary>One clause saying why <paramref name="section"/> produced
        /// nothing, distinguishing "not there" from "could not look". Callers
        /// append their own consequence and finish the sentence.
        ///
        /// FIVE CLAUSES, UNCHANGED, AND NO SIXTH. What moved is what
        /// file-missing means: the slice's own file, not one document for all
        /// nine.</summary>
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
        // The four slots whose files are flat — modelrules, powerlevel,
        // selfcheck and difficulty — are scalars and nothing else. Their loaders
        // would otherwise be four copies of the same forty lines the five older
        // loaders already carry by hand, so the shape lives here once.
        //
        // The five older loaders are NOT routed through this. Their bodies are
        // nested and each walks its own blocks to name an unknown key, and
        // rewriting them to fit would be a change to code Run58 confirmed for
        // no gain.

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
        /// to Info, for the one subsystem whose shipped state is off anyway. It
        /// never touches the unreadable path: that stays an Error whatever the
        /// caller thinks of an absence, because "not there" and "could not look"
        /// are different findings (AGENTS.md section 3).</summary>
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

            // Same rule as the five older loaders: an unrecognised key is
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
            // Presence, exactly as specs/config-surface/spec.md states it: the
            // old document on disk at the same time as any slice file. Not
            // "carries a section" — narrowing it to that would be this class
            // deciding which of two copies of the player's tuning is the real
            // one, which is the decision the refusal exists to refuse.
            var anySlice = 0;
            foreach (var name in Slots)
                if (slots[name].State != State.FileMissing) anySlice++;

            var legacyThere = false;
            try { legacyThere = File.Exists(legacy); }
            catch (Exception e)
            {
                // Could not look. NOT "it is not there" (AGENTS.md section 3).
                // Treated as present, because refusing costs a launch and
                // applying a half-migrated config costs the tuning.
                legacyThere = true;
                Plugin.Log.LogError("ConfigDoc: could not tell whether " + legacy
                    + " exists: " + e.GetType().Name + ": " + e.Message + ". That is NOT the "
                    + "same as it being absent, so it is treated as PRESENT: if any slice "
                    + "file is on disk this launch applies no rule. Fix the error and "
                    + "relaunch.");
            }

            if (legacyThere && anySlice > 0)
            {
                BothLayouts = true;
                Plugin.Log.LogError("ConfigDoc: BOTH CONFIG LAYOUTS ARE ON DISK. "
                    + legacy + " is the pre-4.0 merged document, and " + dir
                    + " holds " + anySlice + " slice file(s). THE MIGRATOR HAS NOT BEEN RUN. "
                    + "No rule is applied this launch and the game runs unmodified: with two "
                    + "copies of the same tuning present, applying either one would mean "
                    + "silently choosing which of your edits count. Move " + FileName
                    + " out of BepInEx\\config (renaming it to " + FileName
                    + ".pre-4.0-backup is what the migrator does) and relaunch.");
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
                    // is the behaviour that was already exercised.
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
                    // key that maps to no member — Elapse.cs returns null and
                    // the feature is off for the launch [measured, Elapse.cs
                    // member Options and its unknown-key walk]. The stamp maps
                    // to no member in any of them. Serving the raw object would
                    // therefore switch Elapse and Fatigue OFF on every launch,
                    // by the stamp this phase just added.
                    //
                    // So the served text is the object minus "_version" and
                    // nothing else. Every other key, comment and trailing comma
                    // survives; the five older loaders do not move; and no POCO
                    // gains a stamp property it has no use for. The four flat
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
                    + "running on built-in defaults. Since the split, one syntax error costs one "
                    + "slice its settings and no other slice anything; it never costs a switch, "
                    + "because the switches are in ckf.hardmode.cfg and were read before this.");
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
        // THIS INSTRUMENT REPORTS THAT IT DID NOT ACT. AGENTS.md section 3.
        //
        // specs/config-surface/spec.md, "Version-stamped upgrade fills new keys
        // only", wants a file whose stamp is older than the assembly's to have
        // the keys the running version added written into it from the embedded
        // default. THIS ASSEMBLY CARRIES NO EMBEDDED DEFAULTS: Defaults.cs's own
        // header records that they were removed and now travel as loose files in
        // the release zip, and Defaults.Install writes nothing at all. So there
        // is nothing here to fill a new key FROM, and a silent pass would read
        // as "checked, nothing to do".
        //
        // What this does instead: read every stamp, compare it to
        // Defaults.DocVersion, and say out loud which files are behind and that
        // NOTHING WAS FILLED IN. The fill half arrives with whatever restores an
        // embedded or packaged default; until then the upgrade is the player
        // extracting the release zip, which is what Defaults.Install already
        // tells them.
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

            // NOT APPLIED, AND SAID SO. implants-global.json is read, stamped
            // and guarded here, and nothing consumes its three numbers. The
            // live effect still comes from the one unscoped ImplantModel rule in
            // ckf.hardmode.rules.json. A file that is read and not applied, with
            // nothing in the log, is the silent instrument AGENTS.md section 3
            // is about.
            //
            // CORRECTION, Phase 7. This block used to say "its four numbers have
            // no expander yet". THREE numbers (implantStressClampMin was removed
            // per David; it never binds), and there IS an expander now —
            // Implants.cs — which refuses to emit from this file while the
            // source MULTIPLY is still live in ckf.hardmode.rules.json.
            // Implants.RefuseGlobal carries the full statement; this line stays
            // because ConfigDoc is what actually read the file and a reader that
            // goes quiet about its own subject is the defect, not the fix.
            var ig = slots[ImplantsGlobal];
            if (ig.State == State.Ok)
                Plugin.Log.LogInfo("ConfigDoc: " + FileFor(ImplantsGlobal) + " was read and "
                    + "guarded, and IT IS NOW THE ONLY SOURCE of the three blanket implant "
                    + "multipliers. Implants.ExpandGlobal emits them from here, against every "
                    + "ImplantModel row with no selector -- all 198, INCLUDING the 20 drone "
                    + "modules in slots 100-107 that no table shows, which is accepted and not "
                    + "a bug. Editing this file now changes the game. THIS LINE USED TO SAY "
                    + "'NOTHING APPLIED IT ... editing this file changes nothing until Phase 9 "
                    + "deletes that rule'; Phase 9 deleted it, in the same commit that wired "
                    + "this up, because either half alone is a balance change. See the "
                    + "Implants: lines below for the numbers.");
        }
    }
}
