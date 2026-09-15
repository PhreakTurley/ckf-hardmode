// GearClasses — the gear-class lever sheet, expanded into rules at load.
//
// WHAT A LEVER SHEET IS, AND WHY THE EXPANSION IS HERE
//
// A DIRECT OVERLAY's rows are rows of a game table: the filename names the
// table, the header names game columns, the first column is the table's id
// column. Overlays.cs already parses those and Phase 4 added thirty-three of
// them without one line of loader code.
//
// A LEVER SHEET's rows are player concepts. `gear-classes.csv` has ten rows,
// one per tuned player weapon class, and twenty-two columns that are tuning
// levers rather than game columns. One row expands into writes across every
// player weapon of that class. That expansion happens HERE, in the plugin, at
// load — never in the editor. design.md section 1, "Why the mod expands, not
// the GUI", is settled: a compiled mirror beside the sheet would be a second
// file that can disagree with the first, and it would mean hand-editing the
// CSV does nothing until someone opens the GUI and presses Save. Editing the
// sheet in a spreadsheet with the game and the editor closed has to work.
//
// WHAT IT REPLACES
//
// Sixteen hand-maintained `whereMin`/`whereMax` pairs in
// ckf.hardmode.rules.json, each `multiply RecoilRate2 x1.8`, copied out of
// overlays/_reference/player-vs-enemy-gear.md. They are byte-identical to that
// document's sixteen pairs [measured] and they drifted in BOTH directions:
//
//   - they caught 30 drone weapons at ids 26000-26029 that did not exist when
//     the list was written, multiplying a `RecoilRate2` nobody asked to move;
//   - they missed 10 player assault rifles that BECAME player gear when the
//     borrowed enemy ladders were split out into 900160-900199 and every
//     archetype was repointed. The list was never regenerated.
//
// Regenerating that list by hand on each game update is the same mechanism
// with a shorter fuse. So this file holds no ids at all. It derives the
// partition from the pointer data on every launch.
//
// THE PARTITION, AND WHICH MonsterTypeModel IS THE RIGHT ONE
//
// `WeaponModel` has no column marking a row player or enemy — `ServiceOptionId`,
// `FactionId`, `Rarity`, `Cost`, `PowerLevel` and `Locked` were each checked
// and each fails [measured, design.md section 5]. The canonical definition is
// overlays/_reference/player-vs-enemy-gear.md: a row is enemy gear when
// `MonsterTypeModel` points at it, and the player set is everything else.
//
// WHICH TABLE, THOUGH. This is the load-bearing decision in the file.
//
//   The SHIPPED MonsterTypeModel has 208 distinct `WeaponTypeId` values and
//   puts class 3 at 25 player / 51 enemy. [measured]
//
//   MonsterTypeModel AFTER this mod's own enemy overlay has 405 and puts
//   class 3 at 33 / 43. [measured]
//
// design.md section 5 states class 3 = 33/43 and class 10 = 33/40. Only the
// second reading reproduces BOTH, and the difference is exactly the ladder
// split-out described above. So the set that matters is the POST-OVERLAY one —
// what enemies actually carry once this mod has loaded — and it is read from
// ckf.hardmode.d/MonsterTypeModel.csv, a file this plugin already owns.
//
// WHY NOT READ THE GAME TABLE. Two reasons, both recorded rather than assumed.
// RowClone.cs says it outright — "Do not serve into a whole-table read … Nothing
// during play enumerates a whole table" — after Run 42, where a bulk
// ReadArmors() call ended in a mission dying on a null armour. And at the
// moment this runs there is no database instance to call a bulk reader on:
// the materializers are static, and the only way the diagnostic plugin ever
// gets one is by patching instance Read* methods and waiting for the game.
//
// AN UNREADABLE POINTER FILE IS NOT AN EMPTY ONE. AGENTS.md section 3. If
// MonsterTypeModel.csv is missing, has no `WeaponTypeId` column, or has a row
// with a blank one, this file emits NO RULES AT ALL and says why. The
// alternative — an empty enemy set — silently turns every class lever into a
// lever that buffs guards, and looks exactly like a clean run.

using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text.Json;

namespace CKFHardMode
{
    internal static class GearClasses
    {
        internal const string SheetName   = "gear-classes.csv";
        internal const string PointerFile = "MonsterTypeModel.csv";
        internal const string IdColumn    = "WeaponId";
        internal const string ClassColumn = "WeaponClass";
        internal const string PointerCol  = "WeaponTypeId";
        internal const string Model       = "WeaponModel";

        // design.md section 5. Ten of the sixteen classes get a lever row.
        internal static readonly int[] LeverClasses = { 1, 2, 3, 4, 5, 6, 10, 11, 12, 14 };

        // Six do not, and each says why in one string that reaches the log. The
        // assertion that no rule names a weapon in these is made over the
        // GENERATED RULES (see the census below), not by reading the sheet.
        //
        // CORRECTION, carried. An earlier version of this task said "14 player
        // class rows" and asked whoever ran it to name "the two classes with no
        // player rows". All sixteen classes have player rows — the smallest is
        // class 7 at one and the largest class 1 at sixty-one. [measured] The
        // gap between 16 and 10 is a scope decision, not a data gap.
        internal static readonly Dictionary<int, string> ExcludedClasses =
            new Dictionary<int, string>
        {
            { 7,  "Canine Attack Rig — a single row, so a class lever is that row with extra steps" },
            { 9,  "DroneAR — drones are out of scope (proposal.md non-goals)" },
            { 16, "Cyber Weapon Claws — tuned item by item in cyberweapons-claws.csv" },
            { 17, "Cyber Weapon Eyes — tuned item by item in cyberweapons-lasers.csv" },
            { 18, "DroneSMG — drones are out of scope (proposal.md non-goals)" },
            { 19, "DroneERifle — drones are out of scope (proposal.md non-goals)" },
        };

        // design.md section 5, in its order. Every one is present in the
        // 2026-09-12 WeaponModel header and not one is an unsuffixed alias.
        // docs/gotchas.md, "Some columns are computed and silently ignore
        // writes": the unsuffixed twins are aliases for the selected firing
        // mode, neither is read-only, and a write to one is taken and
        // discarded with no diagnostic. The sheet writes BallisticDamage1,
        // never BallisticDamage — asserted repo-side over the generated rules
        // by scripts/gear_classes.py, which is where the WeaponModel header is
        // available to check against.
        internal static readonly string[] Levers =
        {
            "Accuracy1", "Accuracy2", "BallisticDamage1", "BallisticDamage2",
            "PhysicalDamage1", "PureDamage1", "PureDamage2", "ActionPoints1",
            "ActionPoints2", "RecoilRate1", "RecoilRate2", "ArmorCritRate1",
            "ArmorCritRate2", "MaxRange", "OptimalRangeA1", "OptimalRangeB1",
            "OptimalRangeA2", "OptimalRangeB2", "FAShots", "CritMultiBase",
            "CritMultiStealth", "ShotVolume",
        };

        private static readonly HashSet<string> LeverSet =
            new HashSet<string>(Levers, StringComparer.Ordinal);

        /// <summary>True when this file is a lever sheet this class expands.
        /// Overlays.Load asks before it derives a table name from the filename:
        /// TableOf("gear-classes.csv") would yield "gear-classesModel" and every
        /// row would build a rule against a table that does not exist, surfacing
        /// only as an orphan warning long afterwards.</summary>
        internal static bool Owns(string fileName) =>
            string.Equals(fileName, SheetName, StringComparison.OrdinalIgnoreCase);

        // ---- the enemy set ---------------------------------------------------

        internal static HashSet<long> EnemyIds { get; private set; }
        internal static int PointerRowsRead { get; private set; }

        /// <summary>The post-overlay MonsterTypeModel pointer set. Returns null
        /// — never an empty set — when the file cannot be read, so that the
        /// caller can tell "no enemies" from "could not look".</summary>
        private static HashSet<long> ReadPointerSet(string dir)
        {
            var path = Path.Combine(dir, PointerFile);
            if (!File.Exists(path))
            {
                Plugin.Log.LogError($"GearClasses: {PointerFile} is not in {dir}, so the "
                    + "player/enemy partition cannot be resolved. NO gear-class rule is "
                    + "emitted this launch. This is a refusal, not an empty answer: "
                    + "treating a missing pointer file as \"no enemies\" would turn every "
                    + "class lever into one that also buffs the guards carrying that class, "
                    + "and it would look exactly like a clean run.");
                return null;
            }

            string[] lines;
            try { lines = File.ReadAllLines(path); }
            catch (Exception e)
            {
                Plugin.Log.LogError($"GearClasses: could not read {path}: {e.Message}. NO "
                    + "gear-class rule is emitted this launch — see the refusal note above.");
                return null;
            }

            if (lines.Length < 2)
            {
                Plugin.Log.LogError($"GearClasses: {PointerFile} has {lines.Length} line(s); "
                    + "a header and at least one data row are needed. NO gear-class rule is "
                    + "emitted this launch.");
                return null;
            }

            var header = Overlays.SplitLine(lines[0], ',');
            int col = Array.FindIndex(header,
                h => string.Equals(h.Trim(), PointerCol, StringComparison.Ordinal));
            if (col < 0)
            {
                Plugin.Log.LogError($"GearClasses: {PointerFile} has no {PointerCol} column "
                    + $"(header: {string.Join(", ", header)}). NO gear-class rule is emitted "
                    + "this launch.");
                return null;
            }

            var ids = new HashSet<long>();
            int rows = 0, blank = 0, bad = 0;
            for (int i = 1; i < lines.Length; i++)
            {
                if (string.IsNullOrWhiteSpace(lines[i])) continue;
                rows++;
                var cells = Overlays.SplitLine(lines[i], ',');
                if (col >= cells.Length) { blank++; continue; }
                var v = (cells[col] ?? "").Trim();
                if (v.Length == 0) { blank++; continue; }
                long id;
                if (!long.TryParse(v, NumberStyles.Integer, CultureInfo.InvariantCulture, out id))
                { bad++; continue; }
                ids.Add(id);
            }

            // A partition built from an incomplete pointer set is worse than no
            // partition: the rows it failed to read are exactly the ones that
            // would then be tuned as player gear. Refuse rather than round down.
            if (blank > 0 || bad > 0)
            {
                Plugin.Log.LogError($"GearClasses: {PointerFile} has {blank} row(s) with a "
                    + $"blank {PointerCol} and {bad} that do not parse as an integer, out of "
                    + $"{rows}. Every monster row must name a weapon for the partition to be "
                    + "complete, so NO gear-class rule is emitted this launch. A partition "
                    + "built from a partly-read pointer file would classify precisely the "
                    + "unreadable rows' weapons as player gear.");
                return null;
            }

            PointerRowsRead = rows;
            Plugin.Log.LogInfo($"GearClasses: {PointerFile} — {rows} monster row(s) read, "
                + $"{ids.Count} distinct {PointerCol} value(s). This is the POST-OVERLAY "
                + "pointer set: what enemies carry once this mod's own enemy-gear overlay "
                + "has repointed the ladders. Reading the game's shipped table instead would "
                + "classify eight player assault rifles as enemy gear (design.md section 5).");
            return ids;
        }

        // ---- expansion -------------------------------------------------------

        /// <summary>Read the sheet and hand every rule it produces to
        /// <paramref name="adopt"/>. Returns the number of sheet rows that
        /// produced a rule, which is what Overlays.Load counts.</summary>
        internal static int Expand(string path, Action<Rule> adopt)
        {
            var dir = Path.GetDirectoryName(path) ?? ".";
            var enemy = ReadPointerSet(dir);
            if (enemy == null) return 0;          // refused above, and said why
            EnemyIds = enemy;

            string[] lines;
            try { lines = File.ReadAllLines(path); }
            catch (Exception e)
            {
                Plugin.Log.LogError($"GearClasses: could not read {path}: {e.Message}");
                return 0;
            }
            if (lines.Length < 2)
            {
                Plugin.Log.LogWarning($"GearClasses: {SheetName} has no data rows.");
                return 0;
            }

            var header = Overlays.SplitLine(lines[0], ',').Select(h => h.Trim()).ToArray();
            int classAt = Array.IndexOf(header, ClassColumn);
            if (classAt < 0)
            {
                Plugin.Log.LogError($"GearClasses: {SheetName} has no {ClassColumn} column "
                    + $"(header: {string.Join(", ", header)}). No rule emitted.");
                return 0;
            }

            // A header column that is neither the class, a known lever nor a
            // control column is named once. Silently ignoring it is how a
            // renamed lever becomes a column nobody writes.
            foreach (var h in header)
            {
                if (h.Length == 0 || h == ClassColumn || LeverSet.Contains(h)) continue;
                if (h.StartsWith("_", StringComparison.Ordinal)) continue;
                Plugin.Log.LogWarning($"GearClasses: {SheetName} header column '{h}' is not "
                    + "one of the 22 levers and is not a control column; it is ignored. "
                    + "Check the spelling against design.md section 5.");
            }

            int rows = 0, emitted = 0, cells = 0, refused = 0;
            var seenClass = new HashSet<int>();

            for (int i = 1; i < lines.Length; i++)
            {
                if (string.IsNullOrWhiteSpace(lines[i])) continue;
                rows++;
                var c = Overlays.SplitLine(lines[i], ',');
                if (classAt >= c.Length) continue;

                int cls;
                if (!int.TryParse((c[classAt] ?? "").Trim(), NumberStyles.Integer,
                                  CultureInfo.InvariantCulture, out cls))
                {
                    Plugin.Log.LogWarning($"GearClasses[{SheetName}:{i + 1}]: "
                        + $"{ClassColumn} '{c[classAt]}' is not an integer class id; "
                        + "the row is skipped.");
                    refused++;
                    continue;
                }

                if (!seenClass.Add(cls))
                    Plugin.Log.LogWarning($"GearClasses[{SheetName}:{i + 1}]: class {cls} "
                        + "has more than one row. Both are expanded and the later one runs "
                        + "second; that is load order, not a merge.");

                string why;
                if (ExcludedClasses.TryGetValue(cls, out why))
                {
                    Plugin.Log.LogWarning($"GearClasses[{SheetName}:{i + 1}]: class {cls} is "
                        + $"an EXCLUDED class ({why}). The row is skipped and no rule names a "
                        + "weapon in it.");
                    refused++;
                    continue;
                }
                if (Array.IndexOf(LeverClasses, cls) < 0)
                {
                    Plugin.Log.LogWarning($"GearClasses[{SheetName}:{i + 1}]: class {cls} is "
                        + "neither one of the ten lever classes nor one of the six excluded "
                        + "ones. The row is skipped — a class in no bucket is a decision "
                        + "nobody has made, not a default.");
                    refused++;
                    continue;
                }

                // Grouped by operation, because ModelRules.Apply runs set, then
                // multiply, then add WITHIN one rule whatever order the columns
                // arrived in. One rule per class rather than one per cell keeps
                // that order deterministic and keeps the plan small: a rule the
                // plan cannot index is tested against every row of its table,
                // and ten such rules cost a tenth of what two hundred would.
                var sets = new Dictionary<string, JsonElement>(StringComparer.Ordinal);
                var muls = new Dictionary<string, JsonElement>(StringComparer.Ordinal);
                var adds = new Dictionary<string, JsonElement>(StringComparer.Ordinal);

                for (int h = 0; h < header.Length && h < c.Length; h++)
                {
                    var col = header[h];
                    if (!LeverSet.Contains(col)) continue;

                    bool ok;
                    var adj = MissionRewards.Adjust.Parse(c[h], out ok);
                    if (!ok)
                    {
                        // THREE-STATE, and this is the branch that makes it worth
                        // it: a cell like "1.8x" parses to "no operation" under a
                        // two-state reader and is indistinguishable from a blank.
                        // Overlays.BuildRule grew a LineResult for the same
                        // reason in Phase 4. Named with sheet, row and column,
                        // which is what the spec's SaveRefused scenario asks the
                        // editor to do on the other side.
                        Plugin.Log.LogWarning($"GearClasses[{SheetName}:{i + 1}]: class "
                            + $"{cls}, column {col}: '{c[h]}' is not an adjustment — expected "
                            + "blank, =N, +N, -N or xN. The cell is ignored; the rest of the "
                            + "row still applies.");
                        refused++;
                        continue;
                    }
                    if (adj.Kind == MissionRewards.AdjustKind.None) continue;   // blank

                    var el = Num(adj.Value);
                    switch (adj.Kind)
                    {
                        case MissionRewards.AdjustKind.Set:      sets[col] = el; break;
                        case MissionRewards.AdjustKind.Multiply: muls[col] = el; break;
                        case MissionRewards.AdjustKind.Add:      adds[col] = el; break;
                    }
                    cells++;
                }

                if (sets.Count == 0 && muls.Count == 0 && adds.Count == 0)
                {
                    // Not a fault. A class row with every cell blank is the
                    // sheet saying "this class is tuned by nothing", which is a
                    // real answer and is printed rather than left to inference.
                    Plugin.Log.LogInfo($"GearClasses: class {cls} has a row and every lever "
                        + "cell is blank, so it emits no rule and its weapons are left as "
                        + "the game ships them.");
                    continue;
                }

                var rule = new Rule
                {
                    Model    = Model,
                    Comment  = $"gear-classes.csv — {ClassColumn} {cls}, player rows only "
                             + $"({enemy.Count} enemy id(s) excluded, resolved at load)",
                    Where    = new Dictionary<string, JsonElement> { { ClassColumn, Num(cls) } },
                    Set      = sets.Count > 0 ? sets : null,
                    Multiply = muls.Count > 0 ? muls : null,
                    Add      = adds.Count > 0 ? adds : null,
                    ExcludeIdColumn = IdColumn,
                    ExcludeIds      = enemy,
                    GearClass       = cls,
                };
                adopt(rule);
                emitted++;
            }

            Plugin.Log.LogInfo($"GearClasses: {SheetName} — {rows} row(s), {emitted} rule(s) "
                + $"emitted, {cells} lever cell(s) set, {refused} cell(s) or row(s) refused. "
                + $"{LeverClasses.Length} lever class(es) declared, {ExcludedClasses.Count} "
                + "excluded and named: "
                + string.Join("; ", ExcludedClasses.OrderBy(k => k.Key)
                                                   .Select(k => k.Key + " " + k.Value)) + ".");

            // WHAT THIS INSTRUMENT CANNOT SAY AT LOAD, said rather than left
            // blank. Nothing here has read WeaponModel — the rows come through
            // the materializer one at a time during play — so the per-class
            // player and enemy COUNTS are not knowable yet. They are reported
            // incrementally by the census below as rows arrive, and completely
            // by scripts/gear_classes.py --census in the repo, where the whole
            // table is on disk.
            Plugin.Log.LogInfo("GearClasses: per-class player/enemy counts are NOT known at "
                + "load — no whole-table read happens here, by design (see the header). The "
                + "census below fills in as the game materializes weapon rows, and "
                + "scripts/gear_classes.py --census is the complete answer.");
            return emitted;
        }

        private static JsonElement Num(double v) =>
            JsonDocument.Parse(v.ToString("R", CultureInfo.InvariantCulture)).RootElement.Clone();

        // ---- the runtime census ---------------------------------------------
        //
        // SAMPLING MOMENT, stated because a count without one cannot be read:
        // this sees every WeaponModel row that is tested against a gear-class
        // rule, and nothing else. A weapon the game never materializes this
        // session is never counted — that is "could not look", not "not there",
        // and the summary says how many rows it did see.
        //
        // Cost after a row's first sighting is one HashSet lookup.

        private static readonly HashSet<long> Seen = new HashSet<long>();
        private static readonly Dictionary<int, int[]> Census = new Dictionary<int, int[]>();
        private static readonly HashSet<int> UnbucketedReported = new HashSet<int>();
        private static int nextFlush = 64;

        internal static void Observe(object row, Type t, long id)
        {
            if (!Seen.Add(id)) return;

            int cls = -1;
            var a = Accessors.Get(t, ClassColumn);
            double v;
            if (a != null && a.TryGetNumber(row, out v)) cls = (int)Math.Round(v);

            int[] slot;
            if (!Census.TryGetValue(cls, out slot)) Census[cls] = slot = new int[3];
            bool lever   = Array.IndexOf(LeverClasses, cls) >= 0;
            bool excl    = ExcludedClasses.ContainsKey(cls);
            bool isEnemy = EnemyIds != null && EnemyIds.Contains(id);

            if (lever) slot[isEnemy ? 1 : 0]++;
            else if (excl) slot[2]++;
            else
            {
                slot[2]++;
                // P1 at runtime: a row in no bucket is named the first time its
                // class turns up, with the row that carried it. This is the
                // whole point of deriving the partition instead of listing ids —
                // a weapon the game ships tomorrow lands in a named bucket, or
                // says which row and why it did not.
                if (UnbucketedReported.Add(cls))
                    Plugin.Log.LogWarning($"GearClasses: {IdColumn} {id} has {ClassColumn} "
                        + $"{cls}, which is neither one of the ten lever classes nor one of "
                        + "the six excluded ones. Nothing tunes it and nothing names it. If "
                        + "the game has shipped a new weapon class, it needs a row in "
                        + $"{SheetName} or an entry in ExcludedClasses. Reported once per "
                        + "class.");
            }

            if (Seen.Count < nextFlush) return;
            nextFlush = Seen.Count < 512 ? Seen.Count * 4 : Seen.Count + 512;
            Flush();
        }

        private static void Flush()
        {
            var parts = new List<string>();
            foreach (var kv in Census.OrderBy(k => k.Key))
            {
                var c = kv.Key;
                var s = kv.Value;
                var role = Array.IndexOf(LeverClasses, c) >= 0
                    ? (s[0] == 0 ? "lever, PLAYER SET EMPTY SO FAR" : "lever")
                    : ExcludedClasses.ContainsKey(c) ? "excluded" : "IN NO BUCKET";
                parts.Add($"{c}: {s[0]}p/{s[1]}e/{s[2]}x {role}");
            }
            Plugin.Log.LogInfo($"GearClasses census after {Seen.Count} distinct weapon row(s) "
                + "seen this session (p=player, e=enemy, x=excluded or unbucketed): "
                + string.Join(" | ", parts)
                + ". Sampling moment: rows tested against a gear-class rule. A class absent "
                + "here has not been materialized yet, which is not the same as having no "
                + "rows — scripts/gear_classes.py --census is the complete answer.");
        }
    }
}
