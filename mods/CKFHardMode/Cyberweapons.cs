// Cyberweapons — the two cyberweapon lever sheets, expanded into rules at load.
//
// WHY THIS IS A SECOND EXPANDER AND NOT A SECOND gear-classes.csv
//
// GearClasses.cs expands ONE row into writes across MANY rows of ONE table: a
// WeaponClass row reaches every player weapon of that class, and the whole
// difficulty there is deciding which rows are the player's.
//
// A cyberweapon row is the other shape. It names ONE weapon, and the thing
// that makes it a lever sheet rather than a direct overlay is that one
// cyberweapon is TWO ROWS IN TWO TABLES. `TalentModel.Weapon` holds the
// `WeaponId`; there are exactly 33 non-zero values in the whole 384-row talent
// table and they are precisely the 33 cyberweapons, one talent per weapon per
// tier [measured, design.md section 6]. The weapon row carries the damage, the
// accuracy and the crit multipliers; the talent row carries the range, the AP
// cost and the effects. A player editing "Photon Lance 3" is editing both.
//
// So ONE SHEET ROW BECOMES TWO RULES — a WeaponModel rule keyed on WeaponId
// and a TalentModel rule keyed on TalentId — and a row that sets nothing on
// one side emits only the other. Neither is a new operator: both are ordinary
// exact-selector rules of the kind ckf.hardmode.rules.json has always carried.
//
// TWO SHEETS, BECAUSE THE LIVE COLUMNS BARELY OVERLAP
//
// Lasers (WeaponClass 17, ImplantClass 32) have no PhysicalDamage and no
// MaxRange — both zero on all 17 — and their reach is the TALENT's Range.
// Claws (WeaponClass 16, ImplantClass 27) have no BallisticDamage and no
// effect columns of any kind, and their range and AP are hard constants.
// [measured, design.md section 6] A single table would be about half empty and
// the lever-sheets spec forbids a column dead for its own rows.
//
// THE CLAW SHEET SHIPS BLANK, AND THAT IS THE POINT
//
// All 16 claws and all 16 claw talents are untouched by the mod today. The
// sheet presents them with their shipped values in `_comment` and no override,
// so the file emits NO RULE AT ALL. A shipped override here would be a balance
// change and proposal.md's non-goals forbid it. The load line below says "0
// rule(s)" for that file rather than staying silent, because a file that
// contributed nothing in silence cannot be told from a file nothing read
// (AGENTS.md section 3).
//
// WHAT THIS FILE DOES NOT DO
//
// NO PLAYER/ENEMY PARTITION. GearClasses needs one and refuses to emit
// anything without it, because a class selector reaches every row of a class.
// These sheets select by exact id, so they reach the 33 rows they name and
// nothing else. The question is still asked, once, repo-side:
// scripts/cyberweapons.py's P4 asserts that no MonsterTypeModel row points at
// any of the 33, in the shipped table and in this mod's own overlay. Today
// neither does — 0 of 208 and 0 of 405. [measured] It is REPO-SIDE ONLY on
// purpose: players have no dumps and design.md section 10 is explicit that no
// runtime behaviour may depend on one being present.
//
// NO CLONE. EVER. design.md section 11 makes splitting a shared row an
// explicit per-row opt-in, and this dialect does not carry one: `_clone` and
// `_serveOn` in a header REFUSE THE WHOLE FILE rather than being ignored.
// RowClone.cs is the path that produces a mission that will not load, and
// Plugin.cs already calls that failure "the mission-hang shape RowClone.cs
// describes". A clone that appears because a generator thought it should is
// exactly the shape that gets there.
//
// KEYS ARE (table, id), NEVER id ALONE. The registry below that refuses a key
// claimed twice is keyed on (model, id). It has to be: this sheet's talent ids
// are 80003-80010, 80015-80038 and 80060, and EffectModel independently
// carries rows 80000-80018, so a registry keyed on the number alone would call
// the laser sheet's TalentModel 80007 a collision with the slot-8 implant
// table's EffectModel 80007 in Phase 7. design.md section 11 names that and
// two more: EffectModel 50000/50001 against MatrixEffectModel 50000/50001.
// Table-wide the overlap is 221 ids between TalentModel and EffectModel and
// 130 between EffectModel and MatrixEffectModel. [measured]

using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text.Json;

namespace CKFHardMode
{
    internal static class Cyberweapons
    {
        internal const string LaserSheet = "cyberweapons-lasers.csv";
        internal const string ClawSheet  = "cyberweapons-claws.csv";

        internal const string WeaponModel = "WeaponModel";
        internal const string TalentModel = "TalentModel";
        internal const string WeaponKey   = "WeaponId";
        internal const string TalentKey   = "TalentId";

        /// <summary>One sheet column, and the one game column of the one game
        /// table it writes.</summary>
        internal sealed class Lever
        {
            internal readonly string Column;   // as it appears in the header
            internal readonly string Model;    // WeaponModel or TalentModel
            internal readonly string Target;   // the game column actually written

            internal Lever(string column, string model, string target)
            {
                Column = column; Model = model; Target = target;
            }
        }

        // THE COLUMN MAP. BEGIN LEVER MAP — scripts/cyberweapons.py's
        // check_map_matches_plugin() scrapes between this marker and END LEVER
        // MAP and refuses if this table and its own disagree, so the two
        // transcriptions cannot drift in silence. Do not reformat the entries
        // without updating that reader; it refuses rather than guessing when it
        // cannot find the markers, because "could not look" is not "they agree".
        //
        // THE ALIAS RULE IS WHY THE NAMES DIFFER ON THE LEFT AND RIGHT.
        // docs/gotchas.md is explicit that WeaponModel's unsuffixed Accuracy,
        // PureDamage, PhysicalDamage, BallisticDamage and ActionPoints are
        // read-only aliases for the SELECTED firing mode: a write to one is
        // taken and discarded with no diagnostic. design.md section 6 names the
        // sheet columns without the suffix, which is the right name for a grid
        // whose rows have no second mode — ModeType2 is -1 on all 33 [measured]
        // — so the suffix is added HERE and the emitted rule always names
        // PureDamage1, never PureDamage. Asserted repo-side against the
        // 2026-09-12 WeaponModel header by scripts/cyberweapons.py's P-COL.
        //
        // SpecialRule AND ApCost ARE HERE AND design.md section 6 DOES NOT LIST
        // THEM. That is a correction, not an addition: they are the two columns
        // the mod's own laser rules actually write. The rules file today sets
        // WeaponModel SpecialRule = 0 on weapons 25000-25015 ("SpecialRule 3
        // 'Rapid Fire' removed") and TalentModel ApCost = 10 on talents
        // 80007-80010 and 80027-80038 ("talent AP cost 2 -> 1"). Both columns
        // are CONSTANT across the 17 shipped rows — SpecialRule 3, ApCost 20
        // [measured] — which is why "no column dead for its own rows" would
        // drop them; that requirement is about columns carrying no lever, and
        // these carry the only lever the mod pulls here. A sheet without them
        // silently gives sixteen lasers back Rapid Fire and sixteen laser
        // talents back their second AP, which is a balance change.
        internal static readonly Lever[] LaserLevers =
        {
            new Lever("PowerLevel",           WeaponModel, "PowerLevel"),
            new Lever("Rarity",               WeaponModel, "Rarity"),
            new Lever("Cost",                 WeaponModel, "Cost"),
            new Lever("Accuracy",             WeaponModel, "Accuracy1"),
            new Lever("PureDamage",           WeaponModel, "PureDamage1"),
            new Lever("BallisticDamage",      WeaponModel, "BallisticDamage1"),
            new Lever("CritMultiBase",        WeaponModel, "CritMultiBase"),
            new Lever("CritMultiStealth",     WeaponModel, "CritMultiStealth"),
            new Lever("PrecisionRule",        WeaponModel, "PrecisionRule"),
            new Lever("SpecialRule",          WeaponModel, "SpecialRule"),
            new Lever("Range",                TalentModel, "Range"),
            new Lever("ApCost",               TalentModel, "ApCost"),
            new Lever("TargetEffect",         TalentModel, "TargetEffect"),
            new Lever("TargetEffectDuration", TalentModel, "TargetEffectDuration"),
            new Lever("SelfEffect",           TalentModel, "SelfEffect"),
        };

        internal static readonly Lever[] ClawLevers =
        {
            new Lever("PowerLevel",       WeaponModel, "PowerLevel"),
            new Lever("Rarity",           WeaponModel, "Rarity"),
            new Lever("Cost",             WeaponModel, "Cost"),
            new Lever("Accuracy",         WeaponModel, "Accuracy1"),
            new Lever("PureDamage",       WeaponModel, "PureDamage1"),
            new Lever("PhysicalDamage",   WeaponModel, "PhysicalDamage1"),
            new Lever("CritMultiBase",    WeaponModel, "CritMultiBase"),
            new Lever("CritMultiStealth", WeaponModel, "CritMultiStealth"),
            new Lever("MaxCharges",       TalentModel, "MaxCharges"),
        };
        // END LEVER MAP

        // The three identity columns. WeaponId keys the WeaponModel rule,
        // TalentId keys the TalentModel rule, WeaponName is there so the file
        // reads in a spreadsheet. NONE of them is a lever: a value in one is
        // never parsed as an adjustment, which is why a WeaponId of 25000 does
        // not become "set WeaponId to 25000".
        internal static readonly string[] Identity = { "WeaponName", WeaponKey, TalentKey };

        // Control columns. `_comment` is accepted and ignored; the two below
        // REFUSE THE WHOLE FILE. See the header on why a clone is never
        // automatic.
        internal static readonly Dictionary<string, string> RefusedControl =
            new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
        {
            { "_clone", "a clone is never emitted from a lever sheet. RowClone.cs is "
                      + "the path that produces a mission that will not load, and "
                      + "design.md section 11 makes splitting a shared row an explicit "
                      + "per-row opt-in that this dialect does not carry." },
            { "_serveOn", "serveOn belongs to a clone rule, and these sheets emit none." },
        };

        private static readonly HashSet<string> IdentitySet =
            new HashSet<string>(Identity, StringComparer.Ordinal);

        /// <summary>True when this file is a lever sheet this class expands.
        /// Overlays.Load asks BEFORE it derives a table name from the filename:
        /// TableOf("cyberweapons-lasers.csv") would yield
        /// "cyberweapons-lasersModel" and every row would build a rule against
        /// a table that does not exist, surfacing only as an orphan warning
        /// long afterwards. Exactly the trap GearClasses.Owns exists for.</summary>
        internal static bool Owns(string fileName) =>
            string.Equals(fileName, LaserSheet, StringComparison.OrdinalIgnoreCase)
         || string.Equals(fileName, ClawSheet,  StringComparison.OrdinalIgnoreCase);

        private static Lever[] LeversFor(string fileName) =>
            string.Equals(fileName, ClawSheet, StringComparison.OrdinalIgnoreCase)
                ? ClawLevers : LaserLevers;

        // ---- the (model, id) registry ---------------------------------------
        //
        // (table, id), NEVER id alone — see the header. Static rather than
        // per-file so that the two sheets cannot both claim one row: they are
        // separate slices with separate toggles, and a weapon named by both
        // would be written twice in whatever order Directory.GetFiles returned.
        //
        // Reset at the head of each Overlays.Load walk by Reset(), so a second
        // load in one process (the test harness does this) does not inherit the
        // first walk's claims and refuse every row.
        private static readonly Dictionary<string, string> Claimed =
            new Dictionary<string, string>(StringComparer.Ordinal);

        private static string KeyOf(string model, long id) =>
            model + " " + id.ToString(CultureInfo.InvariantCulture);

        internal static void Reset() { Claimed.Clear(); }

        // ---- expansion -------------------------------------------------------

        /// <summary>Read one cyberweapon sheet and hand every rule it produces
        /// to <paramref name="adopt"/>. Returns the number of RULES emitted,
        /// which is what Overlays.Load counts — one sheet row can produce two,
        /// one or none.</summary>
        internal static int Expand(string path, Action<Rule> adopt)
        {
            var name = Path.GetFileName(path);
            var levers = LeversFor(name);
            var leverByColumn = levers.ToDictionary(l => l.Column, l => l, StringComparer.Ordinal);

            string[] lines;
            try { lines = File.ReadAllLines(path); }
            catch (Exception e)
            {
                Plugin.Log.LogError($"Cyberweapons: could not read {path}: {e.Message}. "
                    + "NO rule is emitted from this sheet. This is a refusal, not an "
                    + "empty answer: how many rows it holds is not known, because "
                    + "nothing read it.");
                return 0;
            }
            if (lines.Length < 2)
            {
                Plugin.Log.LogWarning($"Cyberweapons: {name} has {lines.Length} line(s); "
                    + "a header and at least one data row are needed. No rule emitted.");
                return 0;
            }

            var header = Overlays.SplitLine(lines[0], ',').Select(h => h.Trim()).ToArray();

            // REFUSED CONTROL COLUMNS, tested before anything is parsed. The
            // whole file is refused rather than the column ignored: a sheet
            // carrying a clone column was authored by something that believed
            // clones come out of here, and the rest of its rows are not more
            // trustworthy than that one.
            foreach (var h in header)
            {
                string why;
                if (!RefusedControl.TryGetValue(h, out why)) continue;
                Plugin.Log.LogError($"Cyberweapons: {name} header carries the control "
                    + $"column '{h}', which this dialect REFUSES: {why} NO rule is "
                    + "emitted from this sheet at all.");
                return 0;
            }

            int wAt = Array.IndexOf(header, WeaponKey);
            int tAt = Array.IndexOf(header, TalentKey);
            if (wAt < 0 || tAt < 0)
            {
                Plugin.Log.LogError($"Cyberweapons: {name} has no {WeaponKey} column "
                    + $"({(wAt < 0 ? "missing" : "present")}) or no {TalentKey} column "
                    + $"({(tAt < 0 ? "missing" : "present")}) (header: "
                    + string.Join(", ", header) + "). One row is two rows in two "
                    + "tables and both keys are needed to split it, so NO rule is "
                    + "emitted — not even the half that could be built.");
                return 0;
            }

            // A header column that is neither identity, a known lever nor a
            // control column is named once. Silently ignoring it is how a
            // renamed lever becomes a column nobody writes.
            foreach (var h in header)
            {
                if (h.Length == 0 || IdentitySet.Contains(h)) continue;
                if (leverByColumn.ContainsKey(h)) continue;
                if (h.StartsWith("_", StringComparison.Ordinal)) continue;
                Plugin.Log.LogWarning($"Cyberweapons: {name} header column '{h}' is not "
                    + $"one of the {levers.Length} levers this sheet declares and is not "
                    + "a control column; it is ignored. Check the spelling against "
                    + "design.md section 6.");
            }

            int rows = 0, emitted = 0, cells = 0, refused = 0;
            int weaponRules = 0, talentRules = 0, blankRows = 0;
            var sharedSeen = new Dictionary<string, List<long>>(StringComparer.Ordinal);

            for (int i = 1; i < lines.Length; i++)
            {
                if (string.IsNullOrWhiteSpace(lines[i])) continue;
                rows++;
                var c = Overlays.SplitLine(lines[i], ',');

                long weaponId, talentId;
                if (wAt >= c.Length || tAt >= c.Length
                    || !long.TryParse((c[wAt] ?? "").Trim(), NumberStyles.Integer,
                                      CultureInfo.InvariantCulture, out weaponId)
                    || !long.TryParse((c[tAt] ?? "").Trim(), NumberStyles.Integer,
                                      CultureInfo.InvariantCulture, out talentId))
                {
                    // BOTH HALVES, or neither. Emitting the weapon rule from a
                    // row whose talent id is unreadable would leave a
                    // cyberweapon with new damage and its old AP cost, which is
                    // a configuration nobody authored.
                    Plugin.Log.LogWarning($"Cyberweapons[{name}:{i + 1}]: {WeaponKey}="
                        + $"'{(wAt < c.Length ? c[wAt] : "<short row>")}' / {TalentKey}="
                        + $"'{(tAt < c.Length ? c[tAt] : "<short row>")}' is not a pair "
                        + "of integer ids. The WHOLE row is skipped, both halves of it: "
                        + "half a cyberweapon is a configuration nobody authored.");
                    refused++;
                    continue;
                }

                // Grouped by model, then by operation. ModelRules.Apply runs
                // set, then multiply, then add WITHIN one rule whatever order
                // the columns arrived in, so one rule per (row, model) keeps
                // that order deterministic and keeps the plan small.
                var sets = new Dictionary<string, Dictionary<string, JsonElement>>(StringComparer.Ordinal);
                var muls = new Dictionary<string, Dictionary<string, JsonElement>>(StringComparer.Ordinal);
                var adds = new Dictionary<string, Dictionary<string, JsonElement>>(StringComparer.Ordinal);

                for (int h = 0; h < header.Length && h < c.Length; h++)
                {
                    Lever lever;
                    if (!leverByColumn.TryGetValue(header[h], out lever)) continue;

                    bool ok;
                    var adj = MissionRewards.Adjust.Parse(c[h], out ok);
                    if (!ok)
                    {
                        // THREE-STATE. A cell like "90x" parses to "no
                        // operation" under a two-state reader and is
                        // indistinguishable from a blank — a tuning change that
                        // silently did not happen. Named with sheet, row and
                        // column, which is what the spec's SaveRefused scenario
                        // asks the editor to do on the other side.
                        Plugin.Log.LogWarning($"Cyberweapons[{name}:{i + 1}]: weapon "
                            + $"{weaponId}, column {lever.Column}: '{c[h]}' is not an "
                            + "adjustment — expected blank, =N, +N, -N or xN. The cell "
                            + "is ignored; the rest of the row still applies.");
                        refused++;
                        continue;
                    }
                    if (adj.Kind == MissionRewards.AdjustKind.None) continue;   // blank

                    var el = Num(adj.Value);
                    switch (adj.Kind)
                    {
                        case MissionRewards.AdjustKind.Set:
                            Bucket(sets, lever.Model)[lever.Target] = el; break;
                        case MissionRewards.AdjustKind.Multiply:
                            Bucket(muls, lever.Model)[lever.Target] = el; break;
                        case MissionRewards.AdjustKind.Add:
                            Bucket(adds, lever.Model)[lever.Target] = el; break;
                    }
                    cells++;

                    // A POINTER CELL IS A REPOINT, NOT AN EDIT OF WHAT IT POINTS
                    // AT. design.md section 11: EffectModel 2051 is Lumen Spear
                    // 4's self effect AND Luem Trident's, so an edit to what
                    // that effect DOES reaches both owners. Writing this cell
                    // does not do that — it aims this one talent somewhere else
                    // — and the distinction is said out loud because the two
                    // read identically in a grid.
                    if (lever.Model == TalentModel
                        && (lever.Target == "SelfEffect" || lever.Target == "TargetEffect"
                            || lever.Target == "MatrixEffect"))
                    {
                        var k = lever.Target + " " + adj.Value.ToString("0.###",
                            CultureInfo.InvariantCulture);
                        List<long> owners;
                        if (!sharedSeen.TryGetValue(k, out owners))
                            sharedSeen[k] = owners = new List<long>();
                        owners.Add(talentId);
                        Plugin.Log.LogInfo($"Cyberweapons[{name}:{i + 1}]: talent "
                            + $"{talentId} {lever.Target} is REPOINTED at "
                            + $"{adj.Value:0.###}. This changes which effect row the "
                            + "talent uses; it does not change what that row does. "
                            + "Nothing in this sheet can edit an EffectModel row — it "
                            + "carries no EffectModel column — so no second owner of a "
                            + "shared effect is touched by this write.");
                    }
                }

                if (sets.Count == 0 && muls.Count == 0 && adds.Count == 0)
                {
                    blankRows++;
                    continue;
                }

                foreach (var pair in new[]
                {
                    new KeyValuePair<string, long>(WeaponModel, weaponId),
                    new KeyValuePair<string, long>(TalentModel, talentId),
                })
                {
                    var model = pair.Key;
                    var id = pair.Value;
                    var s = sets.ContainsKey(model) ? sets[model] : null;
                    var m = muls.ContainsKey(model) ? muls[model] : null;
                    var a = adds.ContainsKey(model) ? adds[model] : null;
                    if (s == null && m == null && a == null) continue;

                    // (model, id), never id alone. See the header.
                    var key = KeyOf(model, id);
                    string already;
                    if (Claimed.TryGetValue(key, out already))
                    {
                        Plugin.Log.LogWarning($"Cyberweapons[{name}:{i + 1}]: ({model}, "
                            + $"{id}) is already written by {already}. One row, one key "
                            + "— two rows writing one key is load order, not a merge, so "
                            + "this one is REFUSED rather than applied second. Note the "
                            + "key is (table, id): TalentModel 80007 and EffectModel "
                            + "80007 are different rows and this registry keeps them "
                            + "apart.");
                        refused++;
                        continue;
                    }
                    Claimed[key] = $"{name}:{i + 1}";

                    var keyColumn = model == WeaponModel ? WeaponKey : TalentKey;
                    adopt(new Rule
                    {
                        Model   = model,
                        Comment = $"{name} — {keyColumn} {id} (weapon {weaponId} / talent "
                                + $"{talentId}, one sheet row split into a {WeaponModel} "
                                + $"rule and a {TalentModel} rule)",
                        Where   = new Dictionary<string, JsonElement> { { keyColumn, Num(id) } },
                        Set      = s,
                        Multiply = m,
                        Add      = a,
                    });
                    emitted++;
                    if (model == WeaponModel) weaponRules++; else talentRules++;
                }
            }

            // THE LOAD-TIME REPORT. Every number it can know, and a named
            // statement of the one it cannot.
            Plugin.Log.LogInfo($"Cyberweapons: {name} — {rows} row(s), {emitted} rule(s) "
                + $"emitted ({weaponRules} {WeaponModel}, {talentRules} {TalentModel}), "
                + $"{cells} lever cell(s) set, {blankRows} row(s) with every cell blank, "
                + $"{refused} cell(s) or row(s) refused. {levers.Length} lever column(s) "
                + "declared for this sheet.");

            // THE RUNTIME SHARED-ROW MARKING. A repoint that lands two talents
            // of this sheet on one effect row is the state design.md section 11
            // is about, and it is named the moment it happens rather than
            // discovered in the editor. Today no cell repoints anything, so
            // this prints nothing — and the line above it prints the count
            // whether or not it is zero, so "no repoints" and "the instrument
            // did not run" stay different answers.
            // `sharedSeen.Count(pred)` does not compile: Dictionary has a Count
            // PROPERTY, so the Linq extension is not reachable through it
            // (CS1955). Counted through Where(...).Count() instead.
            var collided = sharedSeen.Where(k => k.Value.Count > 1).ToList();
            foreach (var kv in collided)
                Plugin.Log.LogWarning($"Cyberweapons: {name} repoints {kv.Value.Count} "
                    + $"talent(s) ({string.Join(", ", kv.Value)}) at the same {kv.Key}. "
                    + "They now SHARE that effect row: an edit to what it does reaches "
                    + "all of them. design.md section 11 makes splitting a shared row an "
                    + "explicit per-row opt-in and nothing here emits a clone.");
            Plugin.Log.LogInfo($"Cyberweapons: {name} — {sharedSeen.Count} distinct "
                + "effect pointer value(s) written by this sheet, "
                + $"{collided.Count} of them landing two or "
                + "more talents on one row. WHAT THIS CANNOT SEE, said rather than left "
                + "blank: the sheet carries no shipped values — a blank cell means "
                + "\"leave that column alone\" — so sharing that exists in the SHIPPED "
                + "data is invisible here. EffectModel 2051 is shipped as both Lumen "
                + "Spear 4's and Luem Trident's self effect and this line will not "
                + "mention it. That half is owned repo-side by scripts/cyberweapons.py's "
                + "P-SHARED, which measures it from the dump, and by the editor's cell "
                + "marking. Nothing here can edit an EffectModel row in any case.");

            if (rows > 0 && blankRows == rows)
                Plugin.Log.LogInfo($"Cyberweapons: {name} produced NO RULE AT ALL, and "
                    + $"that is the intended state: all {rows} row(s) are present with "
                    + "their shipped values in _comment and no override set. The mod "
                    + "does not tune these today and a shipped override would be a "
                    + "balance change (proposal.md non-goals). Said rather than left as "
                    + "a silent zero — a file that contributed nothing cannot otherwise "
                    + "be told from a file nothing read.");

            Plugin.Log.LogInfo($"Cyberweapons: {name} emits no clone and cannot. "
                + "_clone and _serveOn in a header refuse the whole file, and no "
                + "EffectModel or MatrixEffectModel column exists in either sheet, so "
                + "no rule from here can edit a shared effect row's payload. Splitting a "
                + "shared row is an explicit per-row opt-in (design.md section 11) and "
                + "nothing has opted in.");

            return emitted;
        }

        private static Dictionary<string, JsonElement> Bucket(
            Dictionary<string, Dictionary<string, JsonElement>> by, string model)
        {
            Dictionary<string, JsonElement> d;
            if (!by.TryGetValue(model, out d)) by[model] = d =
                new Dictionary<string, JsonElement>(StringComparer.Ordinal);
            return d;
        }

        private static JsonElement Num(double v) =>
            JsonDocument.Parse(v.ToString("R", CultureInfo.InvariantCulture)).RootElement.Clone();

        private static JsonElement Num(long v) =>
            JsonDocument.Parse(v.ToString(CultureInfo.InvariantCulture)).RootElement.Clone();
    }
}
