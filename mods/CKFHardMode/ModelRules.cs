// ModelRules — declarative editing of any database record, at runtime.
//
// The game's data layer is an auto-generated ORM. Every table has a
// materializer named GetRow<Something>Model on RPG.Database.DataDb (static
// content), RPG.Database.GameDb (per-save state) or RPG.Database.CoreDb
// (profile). There are 192 of them, and every model class exposes a public
// getter AND setter for every column.
//
// That gives one clean, uniform interception point: a Harmony postfix on a
// GetRow*Model method sees each record *after* the game has decrypted and
// materialized it, and can rewrite any field before the game ever uses it.
//
// So rules are declarative JSON rather than code — retuning is a text edit
// and a relaunch, no rebuild.
//
// THIS FILE APPLIES RULES AND NOTHING ELSE.
//
// It used to carry the discovery machinery too — dumping a table's columns,
// logging every row, and calling bulk readers to force whole tables through
// the materializer. All of that has moved to the CKF Data Dump plugin, a
// separate assembly with its own config file that shares no code with this
// one and can be installed or removed independently.
//
// The split is not tidiness. Discovery and application want opposite things.
// Discovery wants to touch every table in the database once and is happy to
// cost seconds of load time; application wants to touch only the handful of
// tables a rule targets and runs on the game's hot path for every row it
// reads. Holding both meant paying for a dump you were not taking, and only
// hooking tables you had named twice — in the rules file and again in
// PreloadTables — which is how twelve tables passed for a complete capture
// across a dozen runs.
//
// Write rules against the CSVs the dump plugin produces. Column names are the
// header row of BepInEx/ckf-dump/<Table>.csv.
//
// TWO THINGS LIVE NEXT DOOR AND ARE DRIVEN FROM THE SAME FILE:
//
//   RowClone.cs     a rule carrying "clone"/"as" INSERTS a row rather than
//                   editing one. The GetRow* materializer cannot do that — it
//                   only ever sees rows the game already decided to read — so
//                   cloning hooks the Read* readers instead.
//   Writability.cs  the write-probe behind "modelrules": probeWritableColumns.
//                   Tells you which columns actually accept a write, as
//                   opposed to having a setter that recomputes and discards.

using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Globalization;
using System.Text.Json;
using System.Text.Json.Serialization;
using HarmonyLib;

namespace CKFHardMode
{
    public class Rule
    {
        [JsonPropertyName("model")]    public string Model { get; set; }
        [JsonPropertyName("comment")]  public string Comment { get; set; }
        [JsonPropertyName("where")]    public Dictionary<string, JsonElement> Where { get; set; }
        [JsonPropertyName("whereMin")] public Dictionary<string, double> WhereMin { get; set; }
        [JsonPropertyName("whereMax")] public Dictionary<string, double> WhereMax { get; set; }
        [JsonPropertyName("set")]      public Dictionary<string, JsonElement> Set { get; set; }

        // These four were Dictionary<string, double>. They now take either a
        // number, exactly as before, or a curve object — see Term below. Plain
        // numbers deserialize identically, so every rule written against the
        // old shape still loads.
        [JsonPropertyName("multiply")] public Dictionary<string, JsonElement> Multiply { get; set; }
        [JsonPropertyName("add")]      public Dictionary<string, JsonElement> Add { get; set; }
        [JsonPropertyName("clampMin")] public Dictionary<string, JsonElement> ClampMin { get; set; }
        [JsonPropertyName("clampMax")] public Dictionary<string, JsonElement> ClampMax { get; set; }

        // Row insertion. A rule with "clone" does not edit existing rows at
        // all; it copies one and serves the copy. See RowClone.cs.
        [JsonPropertyName("clone")]   public Dictionary<string, JsonElement> Clone { get; set; }
        [JsonPropertyName("as")]      public Dictionary<string, JsonElement> As { get; set; }
        [JsonPropertyName("serveOn")] public string ServeOn { get; set; }

        // Every property of a rule object this class does not declare.
        //
        // System.Text.Json drops an unknown property without a word, so
        // "mulitply" loaded clean and did nothing. JsonUnmappedMemberHandling
        // would refuse the document outright, but it is .NET 8 and this is
        // net6.0; [JsonExtensionData] is the net6 way to see the same thing,
        // and it warns rather than refusing, so one typo does not cost the
        // whole file. Reported by ModelRules.WarnIfEmpty.
        [JsonExtensionData] public Dictionary<string, JsonElement> Unknown { get; set; }

        // Compiled once at load. Null means the operation was absent.
        [JsonIgnore] internal List<Term> MulTerms { get; set; }
        [JsonIgnore] internal List<Term> AddTerms { get; set; }
        [JsonIgnore] internal List<Term> MinTerms { get; set; }
        [JsonIgnore] internal List<Term> MaxTerms { get; set; }

        [JsonIgnore] internal bool IsClone => Clone != null && Clone.Count > 0;

        // The overlay fast path (see Overlays.cs). A CSV edit line selects one
        // row by one id, and carrying that as a column name and a long rather
        // than a JsonElement keeps a ten-thousand-line overlay to a few small
        // arrays per line instead of a retained JsonDocument each.
        // ---- the gear partition ------------------------------------------
        //
        // Set ONLY by GearClasses.Expand, never by JSON: there is no
        // [JsonPropertyName] on either, so no rules file and no overlay can
        // carry one, and Rule.Unknown will name the spelling if someone tries.
        // This is a SELECTOR, not a new operation — proposal.md's non-goal
        // "no new rule-engine operators" is untouched; set, multiply, add,
        // clampMin, clampMax, clone, as and serveOn are what they were.
        //
        // ExcludeIds is the MonsterTypeModel pointer set resolved at load, and
        // ExcludeIdColumn names the column to test it against. Together with
        // Where = { WeaponClass: N } they express "class N minus the enemy
        // set" without a single hand-maintained id range.
        [JsonIgnore] internal string ExcludeIdColumn { get; set; }
        [JsonIgnore] internal HashSet<long> ExcludeIds { get; set; }

        /// <summary>The WeaponClass this rule came from, for the log line and
        /// the runtime census. Zero on every rule that is not a gear-class
        /// rule.</summary>
        [JsonIgnore] internal int GearClass { get; set; }

        [JsonIgnore] internal string OverlayKeyColumn { get; set; }
        [JsonIgnore] internal long OverlayKeyValue { get; set; }

        // Non-numeric 'set' values from an overlay line — a string or a bool.
        [JsonIgnore] internal Dictionary<string, object> RawSets { get; set; }

        // Position in the loaded file. The only thing guaranteed to differ
        // between two rules — "comment" is optional, and every uncommented rule
        // on one model describes itself identically.
        [JsonIgnore] internal int Index { get; set; }

        // Tracing state. Touched is every column this rule can write, worked
        // out once so the trace can snapshot exactly those and nothing else.
        // Curve-valued entries in 'set'. A plain number, string or bool stays in
        // Set and is written literally; an object is compiled here instead.
        [JsonIgnore] internal List<Term> SetTerms { get; set; }

        [JsonIgnore] internal int Traced { get; set; }
        [JsonIgnore] internal List<string> Touched { get; set; }

        internal string Describe()
        {
            if (!string.IsNullOrWhiteSpace(Comment)) return Comment;
            return (Model ?? "?") + " rule";
        }
    }

    // One right-hand side of a multiply/add/clampMin/clampMax entry.
    //
    // A number is a constant, which is what every rule written before this
    // existed uses. The object form is a straight line in a column's value —
    // written for PowerLevel, which has no interpolation of its own and
    // otherwise needs ten near-identical rules to cover PL 11-20:
    //
    //   "add": { "CritRate": { "perLevelAbove": [10, 2.2] } }
    //
    // reads "+2.2 per level above 10", so PL 11 gets +2.2, PL 20 gets +22, and
    // PL 10 and below get nothing. The value is
    //
    //   base + step * max(0, level - threshold)
    //
    // clamped to "min"/"max" if given. "levelColumn" defaults to PowerLevel;
    // any numeric column on the same row works.
    //
    // "base" is the value at and below the threshold. It defaults to 0 for add
    // and 1 for multiply, which are the neutral elements of those operations,
    // so a row at or below the threshold is left alone. clampMin and clampMax
    // have no usable neutral default — 0 is not neutral for either, it is a
    // floor of zero and a ceiling of zero — so a curve on those two must say
    // what its base is, and a term that does not is refused rather than
    // guessed at.
    internal sealed class Term
    {
        public string Column;
        public bool IsConstant;
        public double Constant;

        public double Base;
        public double Threshold;
        public double Step;
        public string LevelColumn = "PowerLevel";

        // Quantise: the curve advances one step per Every levels rather than
        // every level. For a small integer column — MaxArmorPoints goes 1, 2, 3
        // across a whole shipped family — a per-level slope is meaningless
        // because rounding decides everything. {"perLevelAbove": [10, 1],
        // "every": 4} is +1 at PL 14 and +2 at PL 18, and says so.
        public double Every = 1.0;

        // Geometric instead of linear: Base * Step^steps rather than
        // Base + Step*steps. Step is a ratio per level.
        //
        // This is what a percentage curve wants. "Damage taken falls 4.5% a
        // level" is a ratio; expressed as a linear slope it either stalls at the
        // top of the range or overshoots past it. Paired with GapFrom on a set,
        // it lets a whole ladder be written as the quantity that actually
        // matters and converted back to the column the game stores.
        public bool Geometric;

        // Scale the GAP to this value instead of the value itself:
        //   new = GapFrom - (GapFrom - old) * factor
        // For a column that reads as a percentage of damage prevented, that is
        // the only scaling that means anything. Armour 50 -> 75 halves the
        // damage taken (50% -> 25%); so does 80 -> 90. Multiplying the number
        // instead makes a high-armour row improve far faster than a low one.
        //
        // GapFrom is an asymptote: a falling factor walks the value toward it
        // and never past it. multiply only.
        public double? GapFrom;

        // The split. At or above LinearAbove the column stops behaving like a
        // percentage and is multiplied outright, by 1 + LinearStep*(level -
        // threshold), the way damage is.
        //
        // Armour is why this exists. Below the engine's 95% damage-reduction
        // cap, more armour means proportionally less damage through, so it has
        // to scale on the gap. At and above the cap no further reduction is
        // possible and the extra is buying resistance to degradation instead —
        // a quantity with no ceiling, which scales linearly like everything
        // else. One rule, two regimes, split where the game's own behaviour
        // changes.
        public double? LinearAbove;
        public double? LinearStep;

        // set only: the curve produced the gap, so store GapFrom minus it.
        public bool SetFromGap;
        public double? Floor;
        public double? Ceiling;

        // Resolved on first use and reused while the row type stays the same.
        internal Accessor LevelAcc;
        internal Type LevelAccFor;
    }

    public class RuleFile
    {
        [JsonPropertyName("rules")] public List<Rule> Rules { get; set; } = new List<Rule>();
    }

    internal static class ModelRules
    {
        // model name (e.g. "WeaponModel") -> rules targeting it
        private static readonly Dictionary<string, List<Rule>> ByModel =
            new Dictionary<string, List<Rule>>(StringComparer.OrdinalIgnoreCase);

        // Rules that insert rather than edit. Handed to RowClone.
        private static readonly List<Rule> CloneRules = new List<Rule>();

        // model name -> the compiled plan (see RulePlan.cs), and the map the
        // postfix actually uses. Keying on the MethodBase keeps a Substring and
        // a string hash off the per-row path; the field is replaced wholesale
        // rather than mutated so a reader never sees a half-built dictionary.
        private static readonly Dictionary<string, ModelPlan> Plans =
            new Dictionary<string, ModelPlan>(StringComparer.OrdinalIgnoreCase);
        private static volatile Dictionary<MethodBase, ModelPlan> PlanByMethod =
            new Dictionary<MethodBase, ModelPlan>();

        // ---- property resolution ------------------------------------------
        //
        // Rules are matched and applied per ROW, so a single mistyped column
        // name used to produce one warning per row, forever — JobNodeModel
        // alone is ~1557 rows per read. Worse, the lookup went through
        // AccessTools.Property, which logs its own warning on every miss, so
        // silencing ours would only have halved the flood.
        //
        // Both problems have the same fix: resolve through plain reflection,
        // cache the answer (including the misses), and complain exactly once
        // per type+property.
        private static readonly Dictionary<string, PropertyInfo> PropCache =
            new Dictionary<string, PropertyInfo>(StringComparer.Ordinal);
        private static readonly HashSet<string> WarnedProps =
            new HashSet<string>(StringComparer.Ordinal);
        private static readonly HashSet<string> WarnedErrors =
            new HashSet<string>(StringComparer.Ordinal);

        // 0 = off. Read once at Init; see the "modelrules" section's traceRules.
        internal static int TraceLimit;

        internal static PropertyInfo Prop(Type t, string name)
        {
            if (t == null || string.IsNullOrEmpty(name)) return null;
            var key = t.FullName + "|" + name;
            PropertyInfo p;
            if (PropCache.TryGetValue(key, out p)) return p;
            for (var cur = t; cur != null && cur != typeof(object); cur = cur.BaseType)
            {
                try
                {
                    p = cur.GetProperty(name, BindingFlags.Public | BindingFlags.NonPublic
                                            | BindingFlags.Instance | BindingFlags.DeclaredOnly);
                    if (p != null) break;
                }
                catch { }
            }
            PropCache[key] = p;
            return p;
        }

        // True the first time this type+property is reported FOR THIS
        // DIAGNOSTIC, false after.
        //
        // `what` is part of the key. Without it, Matchable, Writable, Numeric
        // and the level-column warning all shared one namespace per column, so
        // whichever fired first silenced the rest forever — the user was told
        // the write is a no-op and never that the selector can never match, or
        // the other way round. Each diagnostic gets its own once.
        private static bool FirstComplaint(Type t, string name, string what) =>
            WarnedProps.Add((t == null ? "?" : t.FullName) + "|" + name + "|" + what);

        private static readonly string[] DbTypeNames =
        {
            "RPG.Database.DataDb",   // static content: weapons, armor, talents, monsters
            "RPG.Database.GameDb",   // per-save state: this run's characters and monsters
            "RPG.Database.CoreDb",   // profile-level
        };

        // AccessTools.TypeByName walks every loaded assembly and makes
        // UnityEngine.CoreModule throw on the way past, so each call costs
        // fourteen lines of HarmonyX noise. Resolve the three once and hand the
        // list to everyone who needs it.
        internal static readonly List<Type> ResolvedDbs = new List<Type>();

        // The starter file ships with an EMPTY "rules" array and the examples
        // parked under "_examples", which the deserializer ignores.
        //
        // They used to live in "rules". That was a bug with two halves. The
        // engine skips applying them on the run that writes the file, but every
        // later launch loads them like any other rule — so a user who never
        // edited the file got a silent 25% weapon buff and a warning per bad
        // column, forever. And all four examples were wrong: "Damage" and
        // "Cooldown" are not columns (they are BallisticDamage1/2 and
        // RechargeTurns), "Id" is an inherited UI column that reads -1 so it
        // never matches, and CharacterTypeModel is the five-row player-class
        // table with no HitPoints and no numbers at all — enemy archetypes are
        // MonsterTypeModel.
        //
        // Every column named below is verified against a real dump.
        public static string DefaultRulesJson =>
@"{
  ""_readme"": [
    ""Each rule targets one model type and rewrites rows as the game loads them."",
    ""Selectors are 'where' (exact), 'whereMin' and 'whereMax'. Omit all three to match every row."",
    ""Operations apply in order: set, multiply, add, clampMin, clampMax."",
    ""multiply/add/clampMin/clampMax take a number, or { 'perLevelAbove': [level, step] } to slope with PowerLevel."",
    ""'set' takes the same curve, with a 'base' - useful for walking a block of ids one per power level."",
    ""multiply also takes 'gapFrom': scale the gap to that value, not the value. For a percentage column."",
    ""gapFrom pairs with 'linearAbove'/'linearPerLevel': above that value the column multiplies outright."",
    ""A gapFrom multiply leaves a column at 0 alone - 0 means the item has no such stat, not a small one."",
    ""'every': N advances the curve one step per N levels, for small integer columns like MaxArmorPoints."",
    ""'geometric': true makes the step a ratio per level - base * step^n - which is what a percentage wants."",
    ""'gapFrom' on a set means the curve computed the GAP: write the ladder as damage taken, store armour."",
    ""'levelColumn' can be any column - on armour the ID is the ladder position, since PowerLevel is cosmetic."",
    ""A perLevelAbove on clampMin/clampMax must also give a 'base' - the value at and below that level."",
    ""A rule with 'clone' INSERTS a copy of one row instead of editing rows. See _examples."",
    ""Column names come from the CKF Data Dump plugin - the header row of BepInEx/ckf-dump/<Table>.csv."",
    ""Match on the domain id (WeaponId, TalentId, MonsterTypeId). The inherited 'Id' column reads -1."",
    ""Content models (DataDb) change base data. Game* models (GameDb) change this save - prefer set/clampMin there."",
    ""Copy what you want from _examples into rules. Nothing in _examples is applied.""
  ],

  ""rules"": [],

  ""_examples"": [
    {
      ""comment"": ""Every weapon 25% harder. Both firing modes - the unsuffixed columns are read-only."",
      ""model"": ""WeaponModel"",
      ""multiply"": { ""BallisticDamage1"": 1.25, ""BallisticDamage2"": 1.25 }
    },
    {
      ""comment"": ""Enemy weapons only. Enemy ids start at 20000; player weapons are low."",
      ""model"": ""WeaponModel"",
      ""whereMin"": { ""WeaponId"": 20000 },
      ""multiply"": { ""BallisticDamage1"": 1.4, ""BallisticDamage2"": 1.4 }
    },
    {
      ""comment"": ""One specific weapon: Guard Rifle Lvl1 is WeaponId 20000 per the locale file."",
      ""model"": ""WeaponModel"",
      ""where"": { ""WeaponId"": 20000 },
      ""set"": { ""Accuracy1"": 60 }
    },
    {
      ""comment"": ""Enemy archetypes tougher. MonsterTypeModel, not CharacterTypeModel."",
      ""model"": ""MonsterTypeModel"",
      ""multiply"": { ""HitPoints"": 1.5 }
    },
    {
      ""comment"": ""Continue the PL 1-10 slopes past 10 in ONE rule. +2.2 crit per level above 10, so PL 20 gets +22."",
      ""model"": ""MonsterTypeModel"",
      ""whereMin"": { ""PowerLevel"": 11 },
      ""add"": { ""CritRate"": { ""perLevelAbove"": [10, 2.2] },
                ""FlankAllowance"": { ""perLevelAbove"": [10, 2.8] } }
    },
    {
      ""comment"": ""Repair the PL 11 regressions: several columns restart the PL 1-10 sequence at 11."",
      ""model"": ""MonsterTypeModel"",
      ""whereMin"": { ""PowerLevel"": 11 },
      ""clampMin"": { ""MaxTalentCount"": 4, ""CritRate"": 30, ""FlankAllowance"": 115 }
    },
    {
      ""comment"": ""A ceiling. clampMax runs last, so it wins over clampMin where they disagree."",
      ""model"": ""MonsterTypeModel"",
      ""clampMax"": { ""ActionPoints"": 60 }
    },
    {
      ""comment"": ""INSERT a weapon tier 11 by copying tier 10 and making it 15% harder."",
      ""model"": ""WeaponModel"",
      ""clone"": { ""WeaponId"": 20009 },
      ""as"": { ""WeaponId"": 20020 },
      ""multiply"": { ""BallisticDamage1"": 1.15, ""BallisticDamage2"": 1.15 }
    },
    {
      ""comment"": ""...and point the PL 15+ archetypes of one PowerGroup at it."",
      ""model"": ""MonsterTypeModel"",
      ""where"": { ""PowerGroupId"": 1 },
      ""whereMin"": { ""PowerLevel"": 15 },
      ""set"": { ""WeaponTypeId"": 20020 }
    },
    {
      ""comment"": ""Halve one talent's cooldown. The column is RechargeTurns; Adjusted* are read-only."",
      ""model"": ""TalentModel"",
      ""where"": { ""TalentId"": 100 },
      ""multiply"": { ""RechargeTurns"": 0.5 },
      ""clampMin"": { ""RechargeTurns"": 1 }
    },
    {
      ""comment"": ""Scale a whole group of global constants. GroupId is case-sensitive."",
      ""model"": ""RuleModel"",
      ""where"": { ""GroupId"": ""HEAT"" },
      ""multiply"": { ""Value"": 1.5 }
    }
  ]
}
";

        // 3.0: the five [ModelRules] cfg keys are the "modelrules" section of
        // ckf.hardmode.json. The section is new — it has no 2.x sidecar behind
        // it — and it is flat, so ConfigDoc.ReadSection does the grading and
        // the unknown-key report rather than forty lines of it here.
        private sealed class Options : ConfigDoc.IHasUnknownKeys
        {
            // RETIRED 2026-09-13. This used to be
            //     [JsonPropertyName("enabled")] public bool Enabled { get; set; } = true;
            // and Init branched on it. The gate is [Slices] ModelRules in
            // ckf.hardmode.cfg now, because a gate cannot live inside the file
            // it gates (design.md section 3). The key is still PARSED, into a
            // bool? so that "absent" and "false" stay different answers, purely
            // so an existing ckf.hardmode.json is not refused for a key that
            // maps to no member -- the same treatment Fatigue.cs gives the eight
            // flat settings removed on 2026-09-07. NOTHING BRANCHES ON IT;
            // Slices.ReportRetiredGate names it in the log and stops there.
            [JsonPropertyName("enabled")]              public bool? RetiredEnabled { get; set; }
            [JsonPropertyName("traceRules")]           public int TraceRules { get; set; }
            [JsonPropertyName("probeWritableColumns")] public bool ProbeWritableColumns { get; set; }
            // A stringList is a JSON array once it is in the document; it was a
            // comma-separated string only because the .cfg has one line per key.
            [JsonPropertyName("probeTables")]          public List<string> ProbeTables { get; set; }
            [JsonPropertyName("probeOutput")]          public string ProbeOutput { get; set; } = "";
            [JsonExtensionData] public Dictionary<string, JsonElement> Unknown { get; set; }
            public Dictionary<string, JsonElement> UnknownKeys { get { return Unknown; } }
        }

        public static void Init(Harmony harmony, string rulesPath)
        {
            // THE GATE IS READ FIRST, and it is read from ckf.hardmode.cfg. The
            // section below is only settings now, so an unreadable document can
            // no longer take this subsystem's switch with it.
            if (!Slices.On("ModelRules"))
            {
                Plugin.Log.LogInfo(Slices.OffBecause("ModelRules",
                    "no rule is loaded, nothing is hooked, no clone is served and the game's "
                    + "data is left as it ships."));
                return;
            }

            var opt = ConfigDoc.ReadSection<Options>("ModelRules", ConfigDoc.ModelRules,
                "The row-edit engine is OFF this launch: no rule is loaded, nothing is hooked, "
                + "no clone is served and the game's data is left as it ships.");
            if (opt == null) return;

            Slices.ReportRetiredGate("ModelRules", ConfigDoc.ModelRules,
                                     "ModelRules", opt.RetiredEnabled);

            TraceLimit = Math.Max(0, opt.TraceRules);

            // Always on. It changes no result — the numeric conversion is the same
            // round-to-nearest, halves-to-even that Convert.ChangeType did — and it is
            // the single largest saving on the rule hot path.
            Accessors.Configure(true);

            LoadRules(rulesPath);
            Overlays.Load(Path.Combine(Path.GetDirectoryName(rulesPath) ?? ".",
                                       "ckf.hardmode.d"), Adopt);

            // THE PLAN-WIDE TOTAL. Both halves of the mod-slices requirement
            // "A disabled slice never enters the rule plan" are asserted here.
            //
            // The COUNT half: N is every rule that reached Adopt, from the rules
            // file and from every overlay file that was opened. A disabled
            // slice's file was never opened (Overlays.Load asks before the
            // read), so its rows are not in N and allocated no Rule.Index --
            // nextIndex, the one counter Adopt increments, is exactly N plus the
            // clone rules and the rules dropped for having no "model", and it
            // is printed so the two can be reconciled from the log alone.
            //
            // The ORDER half: indices are handed out in walk order, which is the
            // rules file first and then the directory in Ordinal filename order.
            // Dropping a file from that walk shifts the absolute index of
            // everything after it and reorders nothing, so every surviving rule
            // keeps the relative order it had when the slice was on.
            //
            // WHAT THIS CANNOT SAY: how many rules a skipped file would have
            // contributed. Nothing opened it. The files are named instead, so
            // "skipped" and "contributed nothing" stay distinguishable --
            // AGENTS.md §3.
            var skippedFiles = Overlays.SkippedFiles;
            Plugin.Log.LogInfo($"ModelRules: loaded {ByModel.Values.Sum(v => v.Count)} rule(s) "
                + $"across {ByModel.Count} model type(s)"
                + (CloneRules.Count > 0 ? $", plus {CloneRules.Count} clone rule(s)" : "")
                + $"; {nextIndex} load-order index(es) allocated, from "
                // CORRECTION, 2026-09-14 (Phase 9). This clause used to read
                //     "from ckf.hardmode.rules.json plus {Overlays.FilesRead} overlay file(s) read"
                // unconditionally. ckf.hardmode.rules.json is deleted, so that
                // named a file that is not there as a source of the plan on every
                // launch -- the reader would have had to know the count could be
                // zero to tell "contributed nothing" from "was not there".
                // rulesFileRules is -1 until LoadRules sets it, so "not read at
                // all" is a third answer rather than a zero.
                + (rulesFileRules < 0
                    ? "no rules-file read"
                    : rulesFileRules == 0
                        ? $"ckf.hardmode.rules.json (absent, 0 rule(s)) plus {Overlays.FilesRead} overlay file(s) read"
                        : $"ckf.hardmode.rules.json ({rulesFileRules} rule(s)) plus {Overlays.FilesRead} overlay file(s) read")
                + (skippedFiles.Count == 0
                    ? ". No slice file was skipped."
                    : $"; {skippedFiles.Count} file(s) NOT read because their slice is off: "
                      + string.Join(", ", skippedFiles)
                      + ". Their row counts are not included above and are not known — "
                      + "nothing opened them."));

            if (TraceLimit > 0)
                Plugin.Log.LogWarning($"ModelRules: traceRules = {TraceLimit}. Every rule logs "
                    + "its first " + TraceLimit + " row(s) as before -> after. Turn it back to 0 "
                    + "once you have seen what you needed.");

            Writability.Init(opt.ProbeWritableColumns,
                             (opt.ProbeTables ?? new List<string>()).ToArray(),
                             opt.ProbeOutput ?? "");

            if (ByModel.Count == 0 && CloneRules.Count == 0 && !Writability.Enabled)
            {
                Plugin.Log.LogInfo("ModelRules: no rules loaded; nothing hooked.");
                return;
            }

            foreach (var typeName in DbTypeNames)
            {
                var t = AccessTools.TypeByName(typeName);
                if (t == null)
                {
                    Plugin.Log.LogWarning($"ModelRules: could not resolve {typeName}");
                    continue;
                }
                ResolvedDbs.Add(t);
            }

            var postfix = new HarmonyMethod(
                AccessTools.Method(typeof(ModelRules), nameof(AfterGetRow)));

            // Only tables a rule actually targets get hooked. Every hook is a
            // postfix on a method the game calls per row, so hooking a table
            // nothing edits is pure overhead on the hot path. The probe list is
            // the one exception: naming a table there is asking for that hook.
            var matched = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            int patched = 0, seen = 0;

            foreach (var t in ResolvedDbs)
            {
                foreach (var m in AccessTools.GetDeclaredMethods(t))
                {
                    if (!m.Name.StartsWith("GetRow", StringComparison.Ordinal)) continue;
                    if (!m.Name.EndsWith("Model", StringComparison.Ordinal)) continue;
                    seen++;

                    var modelName = m.Name.Substring("GetRow".Length);   // e.g. WeaponModel
                    if (!ByModel.ContainsKey(modelName) && !Writability.Wants(modelName)) continue;

                    try
                    {
                        harmony.Patch(m, postfix: postfix);
                        matched.Add(modelName);
                        patched++;
                    }
                    catch (Exception e)
                    {
                        Plugin.Log.LogWarning($"ModelRules: could not hook {m.Name}: {e.Message}");
                    }
                }
            }

            // Build every plan now rather than on the first row, so the index
            // each model chose is in the log next to the rule counts. A model
            // reported as "no index" tests every rule against every row — fine
            // for a handful of rules, worth a look at several hundred.
            foreach (var kv in ByModel)
            {
                if (!matched.Contains(kv.Key)) continue;
                Plugin.Log.LogInfo("  " + PlanForModel(kv.Key).Describe());
            }

            // A rule aimed at a table that does not exist is silent otherwise —
            // it simply never fires, and the edit you thought you made is not
            // happening. Name them.
            var orphans = ByModel.Keys.Where(k => !matched.Contains(k))
                                      .OrderBy(k => k, StringComparer.Ordinal).ToList();
            if (orphans.Count > 0)
                Plugin.Log.LogWarning("ModelRules: no materializer for " +
                    string.Join(", ", orphans) + " — rules targeting those will never run. " +
                    "Check the spelling against _coverage.csv from the CKF Data Dump plugin.");

            if (patched == 0 && seen > 0 && ByModel.Count > 0)
                Plugin.Log.LogWarning("ModelRules: nothing hooked, so no rule can fire.");

            if (CloneRules.Count > 0)
                RowClone.Init(harmony, CloneRules, ResolvedDbs);

            // Both halves are known now: which clones exist, and which rules
            // point at an id. A rule left pointing at a clone that was not
            // created stops missions loading, so it is named at load.
            //
            // Runs whether or not there are clone rules. It used to sit inside
            // the branch above, which skipped it exactly when it was most
            // needed: with no clone rules nothing is declared, so every id a
            // rule writes into the reserved range is undeclared — and that is
            // the answer the check exists to give.
            RowClone.WarnAboutDanglingReferences(ByModel.Values.SelectMany(v => v));

            // SelfCheck is initialised from Plugin.Load, not here, so that its
            // own settings are honoured even when this subsystem is off. It
            // reads ResolvedDbs, which this method fills above.
        }

        private static void LoadRules(string path)
        {
            try
            {
                if (!File.Exists(path))
                {
                    // CORRECTION, 2026-09-14 (Phase 9). These four lines used to be
                    //
                    //     Directory.CreateDirectory(Path.GetDirectoryName(path));
                    //     File.WriteAllText(path, DefaultRulesJson);
                    //     Plugin.Log.LogInfo($"ModelRules: wrote a starter rules file to {path}");
                    //     Plugin.Log.LogInfo("ModelRules: 'rules' is empty, so nothing is applied. ...");
                    //
                    // and they WROTE THE FILE BACK. That was right while
                    // ckf.hardmode.rules.json was the mod's content: a first launch
                    // with no rules file got a commented starter one to edit. It is
                    // wrong now and it is not a tidy-up -- the file was DELETED on
                    // 2026-09-14 (its 269 rules are all in ckf.hardmode.d), and this
                    // branch would have re-created it on the very next launch, at
                    // Info, in the directory the deletion had just cleared. Defaults
                    // would then have counted it present, and every later launch
                    // would read a file the 4.0 layout says does not exist.
                    //
                    // Nothing else calls DefaultRulesJson now. It is left declared
                    // (member DefaultRulesJson) rather than deleted, because it is
                    // the only remaining description of the rules dialect in this
                    // assembly and scripts/validate_rules.py grades against the same
                    // grammar.
                    //
                    // THIS CLASS NO LONGER WRITES ANYTHING TO THE CONFIG DIRECTORY.
                    Plugin.Log.LogInfo($"ModelRules: no {Path.GetFileName(path)} in "
                        + $"{Path.GetDirectoryName(path)}; 0 rule(s) adopted from it. This is "
                        + "the 4.0 layout and it is EXPECTED -- Plugin.Load has already said "
                        + "so by name above. The file is NOT re-created: what it held is in "
                        + ConfigDoc.DirName + ", which is walked next, and writing a starter "
                        + "file back into a directory it was deleted from would make the next "
                        + "launch read a layout this one says does not exist.");
                    rulesFileRules = 0;
                    return;   // nothing to load, and nothing written
                }

                var opts = new JsonSerializerOptions { ReadCommentHandling = JsonCommentHandling.Skip,
                                                       AllowTrailingCommas = true };
                var before = nextIndex;
                var file = JsonSerializer.Deserialize<RuleFile>(File.ReadAllText(path), opts);
                foreach (var r in file?.Rules ?? new List<Rule>()) Adopt(r);

                // CORRECTION, 2026-09-13. This line used to be
                //
                //     "ModelRules: loaded {ByModel.Values.Sum(v => v.Count)} rule(s)
                //      across {ByModel.Count} model type(s)" (+ the clone clause)
                //
                // and it was emitted HERE, which is before Overlays.Load runs.
                // Its total was therefore never the plan: Run63.log lines 32-33
                // read "ModelRules: loaded 293 rule(s) across 8 model type(s)."
                // immediately followed by "Overlays: 4 file(s), 3022 row(s)
                // merged, 372 of them inserts." [measured, Logs/Run63.log] --
                // 293 counted ckf.hardmode.rules.json alone and excluded all
                // 3022 overlay rows, with nothing saying so.
                //
                // The sentence the mod-slices spec pins, "ModelRules: loaded N
                // rule(s) across M model type(s).", now lives at the end of
                // Init, after the overlay directory has been walked, so N is
                // the whole plan and excluding a slice from it means something.
                // What is left here names only this file's own contribution.
                rulesFileRules = nextIndex - before;
                Plugin.Log.LogInfo($"ModelRules: {nextIndex - before} rule(s) adopted from "
                    + $"{Path.GetFileName(path)} (load-order indices {before}"
                    + (nextIndex > before ? $"-{nextIndex - 1}" : " onwards, none")
                    + "). The overlay directory is walked next and the plan-wide total is "
                    + "reported after it.");
            }
            catch (Exception e)
            {
                Plugin.Log.LogError($"ModelRules: failed to read {path}: {e.Message}");
            }
        }

        // Position in load order, shared by the rules file and the overlay
        // directory so that Rule.Index still says which edit runs first.
        private static int nextIndex;

        /// <summary>How many rules ckf.hardmode.rules.json contributed this
        /// launch. -1 means LoadRules did not run at all, 0 means it ran and the
        /// file was not there; the plan summary prints all three differently so
        /// "absent" is never indistinguishable from "not looked at".</summary>
        private static int rulesFileRules = -1;

        // Register one rule, wherever it was read from. The rules file is
        // adopted first and the overlay directory after it, so an overlay line
        // naming a row wins over a broad sweep that also caught it.
        internal static void Adopt(Rule r)
        {
            if (r == null) return;
            r.Index = nextIndex++;
            if (string.IsNullOrWhiteSpace(r.Model))
            {
                // This used to return without a word. A rule with no "model"
                // targets nothing and is dropped, which is indistinguishable
                // from a rule that ran and changed nothing unless it is named.
                Plugin.Log.LogWarning($"ModelRules: rule #{r.Index} has no \"model\", so there is "
                    + "no table for it to target and it is dropped. The number is its position in "
                    + "load order, counting from 0 through the rules file first and then the "
                    + "overlay directory in filename order.");
                return;
            }

            // OrdinalIgnoreCase, matching ByModel's comparer. Ordinal was the
            // bug: "weaponmodel" does not end with "Model" ordinally, so it
            // became "weaponmodelModel" and was then reported as an orphan.
            r.Model = r.Model.EndsWith("Model", StringComparison.OrdinalIgnoreCase)
                    ? r.Model : r.Model + "Model";

            Compile(r);
            WarnIfEmpty(r);

            // A clone rule inserts; it never edits the rows already in the
            // table. Registering it in ByModel as well would apply its multiply
            // to every real row too, which is the opposite of what "clone this
            // one row" asks for.
            if (r.IsClone) { CloneRules.Add(r); return; }

            if (!ByModel.TryGetValue(r.Model, out var list))
                ByModel[r.Model] = list = new List<Rule>();
            list.Add(r);
        }

        // A rule that carries no operation at all.
        //
        // System.Text.Json ignores a property it does not know, so a misspelled
        // "mulitply" produced a rule with every operation list null: registered,
        // matched against every row of its table, and doing nothing. Rule.Unknown
        // is the net6 way to see those spellings — [JsonExtensionData], because
        // JsonUnmappedMemberHandling is .NET 8 — so the misspelling itself is
        // named too.
        //
        // A clone rule is exempt: "clone" plus "as" is a complete instruction on
        // its own, and inserting an unchanged copy under a new id is a real use.
        private static void WarnIfEmpty(Rule r)
        {
            if (r.Unknown != null && r.Unknown.Count > 0)
                Plugin.Log.LogWarning($"ModelRules: rule #{r.Index} (\"{r.Describe()}\") on "
                    + $"{r.Model} carries " + string.Join(", ", r.Unknown.Keys.Select(k => "'" + k + "'"))
                    + ", which this engine does not know. Check the spelling — the operations are "
                    + "set, multiply, add, clampMin, clampMax, clone, as and serveOn. Unknown "
                    + "properties are ignored.");

            if (r.IsClone) return;

            bool any = r.SetTerms != null || r.MulTerms != null || r.AddTerms != null
                    || r.MinTerms != null || r.MaxTerms != null
                    || (r.Set != null && r.Set.Count > 0)
                    || (r.RawSets != null && r.RawSets.Count > 0);
            if (any) return;

            Plugin.Log.LogWarning($"ModelRules: rule #{r.Index} (\"{r.Describe()}\") on {r.Model} "
                + "carries no operation — no set, multiply, add, clampMin, clampMax or clone — so "
                + "it matches rows and changes nothing. The number is its position in load order, "
                + "counting from 0 through the rules file first and then the overlay directory in "
                + "filename order.");
        }

        // ---- curve compilation ----------------------------------------------

        private static void Compile(Rule r)
        {
            // 'set' with a curve needs an explicit base, for the same reason a
            // clamp does: there is no neutral value to fall back on at or below
            // the threshold. {"perLevelAbove": [10, 1], "base": 20009} walks a
            // contiguous block of ids one per level, which is what makes a
            // per-tier pointer one rule instead of ten.
            //
            // MERGED, not assigned. An overlay line arrives with its terms
            // already built (Overlays.cs skips JSON entirely for edit lines),
            // and assigning here would throw every one of them away — a whole
            // CSV would load, report its row count, and change nothing.
            r.SetTerms = Merge(r.SetTerms, Compile(r, Curves(r.Set), double.NaN, "set"));
            r.MulTerms = Merge(r.MulTerms, Compile(r, r.Multiply, 1.0, "multiply"));
            r.AddTerms = Merge(r.AddTerms, Compile(r, r.Add,      0.0, "add"));
            r.MinTerms = Merge(r.MinTerms, Compile(r, r.ClampMin, double.NaN, "clampMin"));
            r.MaxTerms = Merge(r.MaxTerms, Compile(r, r.ClampMax, double.NaN, "clampMax"));
        }

        private static List<Term> Merge(List<Term> existing, List<Term> extra)
        {
            if (extra == null) return existing;
            if (existing == null) return extra;
            existing.AddRange(extra);
            return existing;
        }

        private static List<Term> Compile(Rule r, Dictionary<string, JsonElement> src,
                                          double defaultBase, string op)
        {
            if (src == null || src.Count == 0) return null;
            var terms = new List<Term>(src.Count);
            foreach (var kv in src)
            {
                var t = new Term { Column = kv.Key, Base = defaultBase };

                if (kv.Value.ValueKind == JsonValueKind.Number)
                {
                    t.IsConstant = true;
                    t.Constant = kv.Value.GetDouble();
                    terms.Add(t);
                    continue;
                }

                if (kv.Value.ValueKind != JsonValueKind.Object)
                {
                    Plugin.Log.LogWarning($"ModelRules: '{op}.{kv.Key}' in \"{r.Describe()}\" is "
                        + "neither a number nor a curve object; skipped.");
                    continue;
                }

                JsonElement slope;
                if (!kv.Value.TryGetProperty("perLevelAbove", out slope)
                    || slope.ValueKind != JsonValueKind.Array
                    || slope.GetArrayLength() != 2)
                {
                    Plugin.Log.LogWarning($"ModelRules: '{op}.{kv.Key}' in \"{r.Describe()}\" is an "
                        + "object but has no 'perLevelAbove': [level, step]; skipped.");
                    continue;
                }

                try
                {
                    t.Threshold = slope[0].GetDouble();
                    t.Step      = slope[1].GetDouble();
                }
                catch
                {
                    Plugin.Log.LogWarning($"ModelRules: '{op}.{kv.Key}' in \"{r.Describe()}\" has a "
                        + "non-numeric 'perLevelAbove'; skipped.");
                    continue;
                }

                JsonElement e;
                if (kv.Value.TryGetProperty("base", out e) && e.ValueKind == JsonValueKind.Number)
                    t.Base = e.GetDouble();

                if (double.IsNaN(t.Base))
                {
                    Plugin.Log.LogWarning($"ModelRules: '{op}.{kv.Key}' in \"{r.Describe()}\" is a "
                        + "curve with no 'base'. A clamp has no neutral value to fall back on at or "
                        + "below the threshold, so give it one — {\"perLevelAbove\": [10, 2], "
                        + "\"base\": 40} means 40 up to PL 10 and +2 a level after. Skipped.");
                    continue;
                }
                if (kv.Value.TryGetProperty("geometric", out e)
                    && (e.ValueKind == JsonValueKind.True || e.ValueKind == JsonValueKind.False))
                    t.Geometric = e.GetBoolean();

                if (kv.Value.TryGetProperty("every", out e) && e.ValueKind == JsonValueKind.Number)
                {
                    t.Every = e.GetDouble();
                    if (t.Every < 1.0)
                    {
                        Plugin.Log.LogWarning($"ModelRules: '{op}.{kv.Key}' in \"{r.Describe()}\" "
                            + $"has 'every': {t.Every}, which is not a step size. Using 1.");
                        t.Every = 1.0;
                    }
                }

                if (kv.Value.TryGetProperty("levelColumn", out e) && e.ValueKind == JsonValueKind.String)
                    t.LevelColumn = e.GetString();
                if (kv.Value.TryGetProperty("min", out e) && e.ValueKind == JsonValueKind.Number)
                    t.Floor = e.GetDouble();
                if (kv.Value.TryGetProperty("max", out e) && e.ValueKind == JsonValueKind.Number)
                    t.Ceiling = e.GetDouble();

                if (kv.Value.TryGetProperty("gapFrom", out e) && e.ValueKind == JsonValueKind.Number)
                {
                    if (op == "multiply") t.GapFrom = e.GetDouble();
                    else if (op == "set")
                    {
                        // On a set the curve is the gap and the column takes the
                        // complement: write the ladder as damage taken, store
                        // armour.
                        t.GapFrom = e.GetDouble();
                        t.SetFromGap = true;
                    }
                    else
                        Plugin.Log.LogWarning($"ModelRules: '{op}.{kv.Key}' in \"{r.Describe()}\" "
                            + "has a 'gapFrom', which means something on multiply and on set but "
                            + "not here. Ignored.");
                }

                JsonElement la, ls;
                var hasLa = kv.Value.TryGetProperty("linearAbove", out la)
                            && la.ValueKind == JsonValueKind.Number;
                var hasLs = kv.Value.TryGetProperty("linearPerLevel", out ls)
                            && ls.ValueKind == JsonValueKind.Number;
                if (hasLa || hasLs)
                {
                    if (op != "multiply" || !t.GapFrom.HasValue)
                        Plugin.Log.LogWarning($"ModelRules: '{op}.{kv.Key}' in \"{r.Describe()}\" "
                            + "has 'linearAbove'/'linearPerLevel', which is the upper half of a "
                            + "gapFrom multiply. Needs both a gapFrom and multiply. Ignored.");
                    else if (!hasLa || !hasLs)
                        Plugin.Log.LogWarning($"ModelRules: '{op}.{kv.Key}' in \"{r.Describe()}\" "
                            + "gives only one of 'linearAbove' and 'linearPerLevel'; both are "
                            + "needed to say where the split is and how fast the upper half "
                            + "grows. Ignored.");
                    else
                    {
                        t.LinearAbove = la.GetDouble();
                        t.LinearStep  = ls.GetDouble();
                    }
                }

                terms.Add(t);
            }
            return terms.Count > 0 ? terms : null;
        }

        // The object-valued entries of a 'set' block, which are curves. Plain
        // values are left to Assign.
        private static Dictionary<string, JsonElement> Curves(Dictionary<string, JsonElement> set)
        {
            if (set == null) return null;
            Dictionary<string, JsonElement> hit = null;
            foreach (var kv in set)
                if (kv.Value.ValueKind == JsonValueKind.Object)
                    (hit ??= new Dictionary<string, JsonElement>(StringComparer.Ordinal))[kv.Key] = kv.Value;
            return hit;
        }

        // The level a curve is reading, or the threshold when the column is
        // missing — which makes every curve flat rather than wrong.
        internal static double LevelOf(object row, Term t)
        {
            var a = LevelAccessor(row, t);
            double v;
            return a != null && a.TryGetNumber(row, out v) ? v : t.Threshold;
        }

        // The level column is read once per term per row, so the accessor is
        // parked on the term rather than looked up each time.
        private static Accessor LevelAccessor(object row, Term t)
        {
            var rowType = row.GetType();
            if (!ReferenceEquals(t.LevelAccFor, rowType))
            {
                t.LevelAcc = Accessors.Get(rowType, t.LevelColumn);
                t.LevelAccFor = rowType;
            }
            return t.LevelAcc != null && t.LevelAcc.Exists && t.LevelAcc.Numeric
                 ? t.LevelAcc : null;
        }

        // Evaluate a curve at a level directly, with no row. Used by the
        // load-time check that a pointer curve is backed by clones.
        internal static double EvaluateAt(Term t, double level)
        {
            if (t.IsConstant) return t.Constant;
            var steps = Math.Max(0.0, level - t.Threshold);
            if (t.Every > 1.0) steps = Math.Floor(steps / t.Every);
            var result = t.Geometric ? t.Base * Math.Pow(t.Step, steps)
                                     : t.Base + t.Step * steps;
            if (t.SetFromGap && t.GapFrom.HasValue) result = t.GapFrom.Value - result;
            if (t.Floor.HasValue)   result = Math.Max(result, t.Floor.Value);
            if (t.Ceiling.HasValue) result = Math.Min(result, t.Ceiling.Value);
            return result;
        }

        private static double Evaluate(object row, Term t)
        {
            if (t.IsConstant) return t.Constant;

            var a = LevelAccessor(row, t);
            if (a == null)
            {
                if (FirstComplaint(row.GetType(), t.LevelColumn, "levelColumn"))
                    Plugin.Log.LogWarning($"  {row.GetType().Name}: perLevelAbove names no numeric "
                        + $"column '{t.LevelColumn}', so the curve is flat at its base. Further "
                        + "rows are not reported.");
                return t.Base;
            }
            double level;
            if (!a.TryGetNumber(row, out level)) return t.Base;

            var steps = Math.Max(0.0, level - t.Threshold);

            // One step per Every levels — the number of COMPLETED intervals,
            // not the level count rounded down to a multiple. With step 1 and
            // every 5 that is +1 at the fifth level above the threshold, not
            // +5. Multiplying back was the 2.4.0 bug: it made 'every' scale the
            // increment instead of spacing it.
            if (t.Every > 1.0) steps = Math.Floor(steps / t.Every);

            var result = t.Geometric
                ? t.Base * Math.Pow(t.Step, steps)
                : t.Base + t.Step * steps;

            // On a set, GapFrom means the curve computed the GAP and the column
            // stores the complement — write the ladder as damage taken, store
            // armour. On a multiply it means something else (scale the gap),
            // which is handled where the multiply is applied.
            if (t.SetFromGap && t.GapFrom.HasValue) result = t.GapFrom.Value - result;
            if (t.Floor.HasValue)   result = Math.Max(result, t.Floor.Value);
            if (t.Ceiling.HasValue) result = Math.Min(result, t.Ceiling.Value);
            return result;
        }

        // The kill switch for a half-finished Init.
        //
        // Init installs the postfix below on every hooked materializer BEFORE it
        // builds the plans and hands the clone rules to RowClone. If it throws
        // in between, the game would run with rules half-applied — ordinary
        // edits firing while 'set' rules point at clone ids nothing serves,
        // which is the mission-hang shape RowClone.cs describes. Plugin.Load
        // sets this in its catch, and every patched entry point checks it, so a
        // partial failure leaves the game unmodified instead of half-modified.
        internal static volatile bool Halted;

        internal static void Halt() { Halted = true; }

        // Harmony postfix: runs for every row the game materializes.
        //
        // Rules only. Discovery — dumping columns, forcing whole tables through
        // the materializer, listing what exists — lives in the CKF Data Dump
        // plugin, which is a separate assembly with its own config and shares
        // nothing with this one. This postfix is on the game's hot path for
        // every row it reads, so it does the least work that applying a rule
        // allows.
        //
        // __instance is the database object the game called this materializer
        // on. It is the only thing here SelfCheck needs, and taking it from this
        // hook is what lets SelfCheck run on a rules file with no clone rules:
        // RowClone.Remember used to be the sole source of an instance, and
        // RowClone is only installed when a clone rule exists.
        //
        // ORDERING. MissionRewards patches GameDb.GetRowGameMissionRewardModel
        // too, and a rule naming GameMissionRewardModel puts this postfix on the
        // same method. Both write RewardQuantity, so before this attribute the
        // result depended on which Harmony owner happened to sort first — and
        // MissionRewards caches the first value it sees for the session, so the
        // wrong answer was stable rather than obviously wrong. Harmony runs
        // higher-priority postfixes first, so MissionRewards.AfterGetRowMissionReward
        // is Priority.First and this is Priority.Last: MissionRewards snapshots
        // the game's stock quantity, then the rules engine multiplies it.
        [HarmonyPriority(Priority.Last)]
        public static void AfterGetRow(MethodBase __originalMethod, object __instance,
                                       object __result)
        {
            if (Halted || __result == null) return;

            // One static bool read per row when SelfCheck is off, which is the
            // shipped default. Offer itself is guarded too; this keeps the call
            // off the hot path entirely.
            if (SelfCheck.Wants && __instance != null)
                SelfCheck.Offer(__originalMethod.DeclaringType, __instance);

            ModelPlan plan;
            if (!PlanByMethod.TryGetValue(__originalMethod, out plan))
                plan = Register(__originalMethod);

            plan.Run(__result);

            // Last, so the probe measures the row the game is actually about to
            // use — rules included — and restores it to that same state.
            if (Writability.Enabled) Writability.Observe(plan.ModelName, __result);
        }

        // The plan for one model, built on first ask. Also the seam the
        // offline differential test drives.
        internal static ModelPlan PlanForModel(string modelName)
        {
            ModelPlan plan;
            if (!Plans.TryGetValue(modelName, out plan))
            {
                List<Rule> rules;
                ByModel.TryGetValue(modelName, out rules);
                Plans[modelName] = plan = new ModelPlan(modelName, rules);
            }
            return plan;
        }

        // Cold path, once per hooked materializer. Harmony normally hands back
        // the same MethodBase we patched, but it is not worth betting the hot
        // path on that, so the first row through any method registers it.
        private static ModelPlan Register(MethodBase m)
        {
            lock (PlanByMethod)
            {
                ModelPlan plan;
                if (PlanByMethod.TryGetValue(m, out plan)) return plan;

                plan = PlanForModel(m.Name.Substring("GetRow".Length));

                // Copy-on-write: the postfix reads PlanByMethod without a lock,
                // so it must never see a dictionary mid-resize.
                var next = new Dictionary<MethodBase, ModelPlan>(PlanByMethod);
                next[m] = plan;
                PlanByMethod = next;
                return plan;
            }
        }

        // Per-row exceptions are keyed on the RULE, not the message. A numeric
        // selector pointed at a string column throws a FormatException whose
        // text quotes the offending value, so keying on the message makes every
        // distinct value in the table its own "reported once" — 1,557 of them
        // on JobNodeModel, and the set grows for as long as the game runs.
        internal static void ReportRuleError(string modelName, Rule rule, Exception e)
        {
            var key = modelName + "|#" + rule.Index + "|" + e.GetType().Name;
            if (WarnedErrors.Add(key))
                Plugin.Log.LogWarning($"ModelRules[{modelName}]: {e.GetType().Name}: " +
                    $"{e.Message}  in \"{rule.Describe()}\" (rule #{rule.Index}; "
                    + "reported once, further rows are not logged)");
        }

        // A mistyped selector is worse than a mistyped target: the rule simply
        // never matches and edits silently stop happening. Say so once.
        private static Accessor Matchable(Type t, string name, string clause)
        {
            var a = Accessors.Get(t, name);
            if ((a == null || !a.Exists) && FirstComplaint(t, name, "matchable|" + clause))
                Plugin.Log.LogWarning($"  {t.Name}: '{clause}' names no property '{name}', so " +
                    "the rule can never match. Further rows are not reported.");
            return a != null && a.Exists ? a : null;
        }

        // A numeric selector against a column that holds no number cannot be
        // satisfied. It used to throw a FormatException per row and be reported
        // through the rule-error path; say what is actually wrong instead.
        private static bool Numeric(Accessor a, Type t, string clause)
        {
            if (a.Numeric) return true;
            if (FirstComplaint(t, a.Name, "numeric|" + clause))
                Plugin.Log.LogWarning($"  {t.Name}.{a.Name} is {a.Underlying?.Name}, not a "
                    + $"number, so '{clause}' can never match. Further rows are not reported.");
            return false;
        }

        internal static bool Matches(object row, Rule rule)
        {
            var t = row.GetType();

            // THE GEAR PARTITION, tested before anything else and FAIL-CLOSED.
            //
            // A row whose id column cannot be read does NOT match. That is the
            // safe direction and it is a deliberate choice: the alternative is
            // that a row we could not classify gets tuned as player gear, which
            // for a class enemies also carry means buffing the guards — and it
            // would be silent, because the column reads fine for every other
            // row. "Could not look" is not "not an enemy" (AGENTS.md §3).
            //
            // Matchable/Numeric already warn once per column per type, so a
            // wholesale failure here is named rather than inferred from a rule
            // that quietly stops firing.
            if (rule.ExcludeIdColumn != null)
            {
                var idAcc = Matchable(t, rule.ExcludeIdColumn, "the gear-partition id column");
                if (idAcc == null || !Numeric(idAcc, t, "the gear-partition id column"))
                    return false;
                double idv;
                if (!idAcc.TryGetNumber(row, out idv)) return false;
                var id = (long)Math.Round(idv);

                // The census sees every row tested against a gear-class rule,
                // which is the only sampling moment this instrument has. It
                // dedupes on id, so the cost after a row's first sighting is
                // one HashSet lookup.
                GearClasses.Observe(row, t, id);

                if (rule.ExcludeIds != null && rule.ExcludeIds.Contains(id)) return false;
            }

            // The overlay selector: one number compare, and the most selective
            // thing on the rule.
            //
            // CORRECTION, 2026-09-13. This comment used to read "tested first".
            // It is tested second now — the gear partition above runs ahead of
            // it, because a rule that must not touch enemy gear has to decide
            // that before it decides anything else. No overlay rule carries an
            // ExcludeIdColumn, so for every rule that existed before this change
            // the branch above is one null test and the order is unchanged.
            if (rule.OverlayKeyColumn != null)
            {
                var k = Matchable(t, rule.OverlayKeyColumn, "the overlay id column");
                if (k == null || !Numeric(k, t, "the overlay id column")) return false;
                double kv;
                if (!k.TryGetNumber(row, out kv)) return false;
                if (Math.Abs(kv - rule.OverlayKeyValue) > 1e-9) return false;
            }

            if (rule.WhereMin != null)
                foreach (var kv in rule.WhereMin)
                {
                    var a = Matchable(t, kv.Key, "whereMin");
                    if (a == null || !Numeric(a, t, "whereMin")) return false;
                    double v;
                    if (!a.TryGetNumber(row, out v) || v < kv.Value) return false;
                }

            if (rule.WhereMax != null)
                foreach (var kv in rule.WhereMax)
                {
                    var a = Matchable(t, kv.Key, "whereMax");
                    if (a == null || !Numeric(a, t, "whereMax")) return false;
                    double v;
                    if (!a.TryGetNumber(row, out v) || v > kv.Value) return false;
                }

            if (rule.Where == null || rule.Where.Count == 0) return true;
            foreach (var kv in rule.Where)
            {
                var a = Matchable(t, kv.Key, "where");
                if (a == null) return false;

                if (kv.Value.ValueKind == JsonValueKind.Number)
                {
                    double v;
                    if (a.Numeric)
                    {
                        if (!a.TryGetNumber(row, out v)) return false;
                    }
                    else
                    {
                        // A number matched against a non-numeric column: keep
                        // the old Convert behaviour, which parses "5" out of a
                        // string column rather than refusing outright.
                        var raw = a.GetRaw(row);
                        if (raw == null) return false;
                        try { v = Convert.ToDouble(raw, CultureInfo.InvariantCulture); }
                        catch { return false; }
                    }
                    if (Math.Abs(v - kv.Value.GetDouble()) > 1e-9) return false;
                }
                else if (kv.Value.ValueKind == JsonValueKind.String)
                {
                    var raw = a.GetRaw(row);
                    if (raw == null) return false;

                    // Invariant, like Changes, Label and the numeric branch
                    // above. raw.ToString() used the machine's current culture,
                    // so on a de-DE machine a float column rendered "1,5" and
                    // never matched the "1.5" the rule was written with — and
                    // nothing complained, because the column exists and reads.
                    var text = Convert.ToString(raw, CultureInfo.InvariantCulture);
                    if (!string.Equals(text, kv.Value.GetString(),
                                       StringComparison.Ordinal)) return false;
                }
                else if (kv.Value.ValueKind is JsonValueKind.True or JsonValueKind.False)
                {
                    var raw = a.GetRaw(row);
                    if (raw == null) return false;
                    if (Convert.ToBoolean(raw) != kv.Value.GetBoolean()) return false;
                }
                else
                {
                    // null, [] or {}. There is nothing to compare against, and
                    // the old behaviour was to let the clause pass — which
                    // turned one malformed selector into a whole-table edit.
                    // Refuse instead.
                    if (FirstComplaint(t, kv.Key, "where-value-kind"))
                        Plugin.Log.LogWarning($"  {t.Name}: 'where.{kv.Key}' is "
                            + $"{kv.Value.ValueKind}, which is not a number, a string or a "
                            + "boolean. The rule matches nothing. Further rows are not reported.");
                    return false;
                }
            }
            return true;
        }

        // set -> multiply -> add -> clampMin -> clampMax, always in that order.
        // clampMax runs last so a pair that disagrees resolves to the ceiling.
        internal static void Apply(object row, Rule rule)
        {
            var t = row.GetType();

            // Snapshot before anything moves, and only the columns this rule can
            // write. Off by default: this runs per row.
            Dictionary<string, object> before = null;
            if (TraceLimit > 0 && rule.Traced < TraceLimit)
                before = Snapshot(row, Touched(rule));

            Assign(row, t, rule.Set, "set");

            if (rule.RawSets != null)
                foreach (var kv in rule.RawSets)
                {
                    var a = Accessors.Get(t, kv.Key);
                    if (!Writable(a, kv.Key, t)) continue;
                    ReportWrite(t, a, kv.Key, a.SetRaw(row, kv.Value), Show(kv.Value),
                                "an overlay 'set'");
                }

            if (rule.SetTerms != null)
                foreach (var term in rule.SetTerms)
                {
                    var a = Accessors.Get(t, term.Column);
                    if (!Writable(a, term.Column, t)) continue;

                    // The same guard Arith carries. Without it a 'set' curve on
                    // a string column wrote the number as a literal and on a
                    // bool column turned any non-zero value into true.
                    if (!Numeric(a, t, "a 'set' curve")) continue;

                    var v = Evaluate(row, term);
                    ReportWrite(t, a, term.Column, a.SetNumber(row, v), Show(v), "a 'set' curve");
                }

            if (rule.MulTerms != null)
                foreach (var term in rule.MulTerms)
                {
                    var k = Evaluate(row, term);
                    if (term.GapFrom.HasValue)
                    {
                        var gap = term.GapFrom.Value;

                        // A factor of 0 would close the gap completely — for
                        // armour, total immunity. Nothing sensible asks for
                        // that, so it is treated as a mistake rather than
                        // honoured.
                        if (k <= 0.0)
                        {
                            if (WarnedErrors.Add("gap0|" + term.Column))
                                Plugin.Log.LogWarning($"  {t.Name}.{term.Column}: a gapFrom "
                                    + $"multiply reached {k:0.###}, which would close the gap to "
                                    + $"{gap} entirely. Clamped to 0.01. Check the curve's step.");
                            k = 0.01;
                        }

                        // The linear half, when the rule declares one: above
                        // the split the column is multiplied outright.
                        double split = double.PositiveInfinity, lin = 1.0;
                        if (term.LinearAbove.HasValue)
                        {
                            split = term.LinearAbove.Value;
                            lin = 1.0 + term.LinearStep.Value
                                      * Math.Max(0.0, LevelOf(row, term) - term.Threshold);
                            if (lin < 0.0) lin = 0.0;
                        }

                        // Past the asymptote the gap is negative and scaling it
                        // would push the value backwards. Leave those rows —
                        // that is what the linear half is normally for.
                        // A zero is not a small percentage, it is the absence
                        // of one — Guard Standard armour carries BallisticArmor
                        // 0 and only its Degraded values mean anything. Scaling
                        // the gap from 0 would hand it 35 points of ballistic
                        // armour it never had, so zero stays zero.
                        Arith(row, t, term.Column, ArithOp.Gap, k, gap, split, lin);
                    }
                    else Arith(row, t, term.Column, ArithOp.Multiply, k);
                }

            if (rule.AddTerms != null)
                foreach (var term in rule.AddTerms)
                    Arith(row, t, term.Column, ArithOp.Add, Evaluate(row, term));

            if (rule.MinTerms != null)
                foreach (var term in rule.MinTerms)
                    Arith(row, t, term.Column, ArithOp.ClampMin, Evaluate(row, term));

            if (rule.MaxTerms != null)
                foreach (var term in rule.MaxTerms)
                    Arith(row, t, term.Column, ArithOp.ClampMax, Evaluate(row, term));

            if (before != null) Trace(row, rule, before);
        }

        // ---- tracing ---------------------------------------------------------

        // Every column a rule can write. Worked out once per rule.
        internal static List<string> Touched(Rule rule)
        {
            if (rule.Touched != null) return rule.Touched;
            var cols = new List<string>();
            void Take(IEnumerable<string> names)
            {
                if (names == null) return;
                foreach (var n in names) if (!cols.Contains(n)) cols.Add(n);
            }
            Take(rule.As?.Keys);
            Take(rule.Set?.Keys);
            Take(rule.RawSets?.Keys);
            Take(rule.SetTerms?.Select(x => x.Column));
            Take(rule.MulTerms?.Select(x => x.Column));
            Take(rule.AddTerms?.Select(x => x.Column));
            Take(rule.MinTerms?.Select(x => x.Column));
            Take(rule.MaxTerms?.Select(x => x.Column));
            return rule.Touched = cols;
        }

        // Through Accessors, not PropertyInfo.GetValue.
        //
        // This used to be a second resolution path against the same property
        // cache, and the two did not agree: Accessor.GetRaw hands back the
        // compiled getter's boxed value where GetValue hands back the raw enum,
        // so the trace could report a column the rules engine had read
        // differently. One path now, so the trace says what the engine acted on.
        internal static Dictionary<string, object> Snapshot(object row, List<string> columns)
        {
            var t = row.GetType();
            var snap = new Dictionary<string, object>(columns.Count, StringComparer.Ordinal);
            foreach (var c in columns)
            {
                var a = Accessors.Get(t, c);
                if (a == null || !a.Exists) continue;
                snap[c] = a.GetRaw(row);
            }
            return snap;
        }

        // Which row this was. Every table's key is <Name>Id — WeaponModel.WeaponId,
        // MonsterTypeModel.MonsterTypeId — and the inherited Id reads -1, so it is
        // no use here. PowerLevel comes along when the row has one, because a
        // perLevelAbove curve is only legible next to the level it was fed.
        internal static string Label(object row)
        {
            var t = row.GetType();
            var name = t.Name.EndsWith("Model", StringComparison.Ordinal)
                ? t.Name.Substring(0, t.Name.Length - "Model".Length) : t.Name;

            // Through Accessors, like Snapshot and Changes, so the label and the
            // values beside it come off one resolution path.
            string id = "?";
            var key = Accessors.Get(t, name + "Id");
            var keyRaw = key == null || !key.Exists ? null : key.GetRaw(row);
            if (keyRaw != null) id = Convert.ToString(keyRaw, CultureInfo.InvariantCulture);

            var pl = Accessors.Get(t, "PowerLevel");
            var plRaw = pl == null || !pl.Exists ? null : pl.GetRaw(row);
            string level = plRaw == null
                         ? null : Convert.ToString(plRaw, CultureInfo.InvariantCulture);

            return $"{t.Name}[{id}]" + (level == null ? "" : $" PL {level}");
        }

        internal static string Changes(object row, Dictionary<string, object> before)
        {
            var t = row.GetType();
            var parts = new List<string>();
            foreach (var kv in before)
            {
                var acc = Accessors.Get(t, kv.Key);
                if (acc == null || !acc.Exists) continue;
                var now = acc.GetRaw(row);
                var a = Convert.ToString(kv.Value, CultureInfo.InvariantCulture);
                var b = Convert.ToString(now, CultureInfo.InvariantCulture);
                if (!string.Equals(a, b, StringComparison.Ordinal))
                    parts.Add($"{kv.Key} {a} -> {b}");
            }
            return string.Join(", ", parts);
        }

        private static void Trace(object row, Rule rule, Dictionary<string, object> before)
        {
            var changes = Changes(row, before);

            // A rule that matched and moved nothing is the interesting case —
            // that is what a read-only column, or a clamp that was already
            // satisfied, looks like. Say so rather than printing nothing.
            rule.Traced++;
            Plugin.Log.LogInfo($"  trace #{rule.Index} {Label(row)}: "
                + (changes.Length > 0 ? changes : "matched, nothing changed")
                + $"   [{rule.Describe()}]"
                + (rule.Traced == TraceLimit ? "  (last trace for this rule)" : ""));
        }

        // The "as" block of a clone rule, and the "set" block of any rule: a
        // literal write, no arithmetic.
        //
        // `block` is "set" or "as", and it is only used in diagnostics — except
        // for one case: an object under "set" is a curve, compiled into SetTerms
        // at load, so it is not something this method should touch or complain
        // about. An object anywhere else has nowhere to go and is reported.
        internal static void Assign(object row, Type t, Dictionary<string, JsonElement> values,
                                    string block)
        {
            if (values == null) return;
            foreach (var kv in values)
            {
                var a = Accessors.Get(t, kv.Key);
                if (!Writable(a, kv.Key, t)) continue;

                switch (kv.Value.ValueKind)
                {
                    case JsonValueKind.Number:
                        var d = kv.Value.GetDouble();
                        if (a.Numeric)
                            ReportWrite(t, a, kv.Key, a.SetNumber(row, d), Show(d),
                                        "'" + block + "'");
                        else
                        {
                            var conv = Converted(d, a);
                            ReportWrite(t, a, kv.Key,
                                conv == null ? WriteResult.Conversion : a.SetRaw(row, conv),
                                Show(d), "'" + block + "'");
                        }
                        break;

                    case JsonValueKind.String:
                        var s = kv.Value.GetString();

                        // A JSON string on a numeric column used to go to SetRaw
                        // untouched, so {"WeaponTypeId": "20020"} — a plausible
                        // typo — loaded clean, matched rows and changed nothing.
                        // Parse it invariantly instead, the way every other
                        // number in this file is read. A string that is not a
                        // number (an enum member's name, say) still cannot be
                        // written, but it is now reported rather than dropped.
                        if (a.Numeric)
                        {
                            double parsed;
                            if (double.TryParse(s, NumberStyles.Float,
                                                CultureInfo.InvariantCulture, out parsed))
                                ReportWrite(t, a, kv.Key, a.SetNumber(row, parsed),
                                            Show(parsed), "'" + block + "'");
                            else if (FirstComplaint(t, kv.Key, "assign-string-not-number"))
                                Plugin.Log.LogWarning($"  {t.Name}.{kv.Key} is "
                                    + $"{a.Underlying?.Name}, and '{block}' gives it the string "
                                    + $"\"{s}\", which is not a number in invariant form. Nothing "
                                    + "is written; further rows are not reported.");
                        }
                        else ReportWrite(t, a, kv.Key, a.SetRaw(row, s), s, "'" + block + "'");
                        break;

                    case JsonValueKind.True:
                    case JsonValueKind.False:
                        var b = kv.Value.GetBoolean();
                        ReportWrite(t, a, kv.Key, a.SetRaw(row, b),
                                    b ? "true" : "false", "'" + block + "'");
                        break;

                    default:
                        // null, [], {} — and {} under "set" is a curve, handled
                        // by SetTerms. Everything else has no value to write and
                        // used to be dropped without a word.
                        if (kv.Value.ValueKind == JsonValueKind.Object
                            && string.Equals(block, "set", StringComparison.Ordinal)) break;
                        if (FirstComplaint(t, kv.Key, "assign-kind"))
                            Plugin.Log.LogWarning($"  {t.Name}: '{block}.{kv.Key}' is "
                                + $"{kv.Value.ValueKind}, which is not a number, a string or a "
                                + "boolean, so there is nothing to write. Further rows are not "
                                + "reported.");
                        break;
                }
            }
        }

        // A number on a non-numeric column, converted the way the old code did.
        // Returns null when it will not convert, which SetRaw reports as
        // NullValue rather than throwing on the game's call path.
        private static object Converted(double d, Accessor a)
        {
            try { return Convert.ChangeType(d, a.Underlying, CultureInfo.InvariantCulture); }
            catch { return null; }
        }

        // The arithmetic a term asks for, as an operand rather than a lambda.
        //
        // Every call site used to build a fresh closure per ROW — one allocation
        // per term per row on a reader that hands back ~1,557 rows — which is
        // exactly the cost Accessors.cs and RulePlan.cs exist to avoid. The
        // results are unchanged: each case below is the body of the lambda it
        // replaced.
        private enum ArithOp { Multiply, Add, ClampMin, ClampMax, Gap }

        private static void Arith(object row, Type t, string name, ArithOp op, double k,
                                  double gap = 0.0, double split = double.PositiveInfinity,
                                  double lin = 1.0)
        {
            var a = Accessors.Get(t, name);
            if (!Writable(a, name, t)) return;
            if (!Numeric(a, t, "an arithmetic operation")) return;

            double cur;
            if (!a.TryGetNumber(row, out cur)) return;

            double next;
            switch (op)
            {
                case ArithOp.Multiply: next = cur * k;         break;
                case ArithOp.Add:      next = cur + k;         break;
                case ArithOp.ClampMin: next = Math.Max(cur, k); break;
                case ArithOp.ClampMax: next = Math.Min(cur, k); break;
                default:
                    next = cur <= 0.0   ? cur
                         : cur >= split ? cur * lin
                         : cur >= gap   ? cur
                         :                gap - (gap - cur) * k;
                    break;
            }

            ReportWrite(t, a, name, a.SetNumber(row, next), Show(next),
                        "an arithmetic operation");
        }

        // A write that was attempted and rejected, once per (type, column,
        // reason). An overflow on an int column — "multiply": {"X": 1e7} on a
        // column holding 400 — used to leave the column at 400 and print
        // "matched, nothing changed", which names neither the column nor the
        // cause.
        private static void ReportWrite(Type t, Accessor a, string name, WriteResult r,
                                        string value, string clause)
        {
            if (r == WriteResult.Ok) return;
            if (!FirstComplaint(t, name, "write|" + r)) return;

            Plugin.Log.LogWarning($"  {t.Name}.{name}: {clause} could not write {value} — "
                + Accessors.Why(r, a) + ". The column is unchanged; further rows are not "
                + "reported.");
        }

        private static string Show(double d) => d.ToString("0.####", CultureInfo.InvariantCulture);

        private static string Show(object v) =>
            v == null ? "null" : Convert.ToString(v, CultureInfo.InvariantCulture);

        internal static Type Underlying(PropertyInfo p) =>
            Nullable.GetUnderlyingType(p.PropertyType) ?? p.PropertyType;

        internal static bool Writable(Accessor a, string name, Type t)
        {
            if (a == null || !a.Exists)
            {
                if (FirstComplaint(t, name, "writable-missing"))
                    Plugin.Log.LogWarning($"  {t.Name}: no property named '{name}' " +
                        "(the real column names are the header row of " +
                        "BepInEx/ckf-dump/" + t.Name + ".csv, written by the CKF Data Dump " +
                        "plugin). This rule will " +
                        "do nothing; further rows are not reported.");
                return false;
            }
            if (!a.CanWrite)
            {
                if (FirstComplaint(t, name, "writable-readonly"))
                    Plugin.Log.LogWarning($"  {t.Name}.{name} is read-only. This rule will do " +
                        "nothing; further rows are not reported. Turn on probeWritableColumns " +
                        "in the \"modelrules\" section of ckf.hardmode.json for the full list " +
                        "of what this table accepts.");
                return false;
            }
            return true;
        }
    }
}
