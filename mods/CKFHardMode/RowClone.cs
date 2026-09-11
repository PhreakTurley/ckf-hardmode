// RowClone — inserting rows the shipped database does not contain.
//
// WHY THIS IS A SEPARATE MECHANISM FROM ModelRules
//
// The rule engine is a postfix on GetRow<X>Model, the per-row materializer.
// That hook can rewrite anything, but it only ever sees rows the game has
// already decided to read, so it cannot add one. Everything the shipped tables
// stop short of therefore stayed out of reach:
//
//   WeaponModel / ArmorModel      PowerLevel columns end at 10; a PL 11-20
//                                 archetype re-uses the tier-10 row, so any
//                                 edit to it also lands on PL 10.
//   MonsterGroupMemberModel       MinPowerLevel gates end at 8, so squad
//                                 composition is fully saturated by PL 8 and
//                                 re-spacing the gates is a redistribution,
//                                 never a net increase.
//   MonsterTalentModel            PL-banded talent tiers stop at "PL 9+".
//   EffectModel                   74 unreferenced rows exist and can be
//                                 repurposed, but there are no spare armor
//                                 rows at all.
//
// HOW A SYNTHETIC ROW IS BUILT
//
// Not by constructing one. Every DataDb model is re-materialized fresh out of
// the content database on each read, so asking the game for the source row
// hands back a private, fully-populated object that nothing else holds a
// reference to. The clone is that object with the 'as' block and the rule's
// own operations written over it. No IL2CPP construction, no column left
// unset, and no risk of a half-built row reaching the game.
//
// One consequence worth knowing: the source row arrives through GetRow*, so
// any ordinary rule matching it has ALREADY been applied when the clone is
// taken. A clone of WeaponId 20009 inherits whatever your other rules did to
// 20009, and then gets its own operations on top.
//
// HOW IT IS SERVED
//
// The readers are the only other way into a table. From CoreRPG_v1.dll, the
// shapes that matter are:
//
//   ReadWeapon(long id)                                        -> WeaponModel
//   ReadWeapons()                                              -> List<WeaponModel>
//   ReadMonsterTypeByPowerGroupId(long groupId)                -> List<MonsterTypeModel>
//   ReadMonsterGroupMembersByGroup(long, long, long, long)     -> List<MonsterGroupMemberModel>
//   ReadMonsterTalents(long group, long powerLevel)            -> List<MonsterTalentModel>
//
// so a clone is hooked onto all three kinds at once: the by-id reader (so
// another row can point at it), the filtered list readers (so it turns up in
// the pool the game rolls from), and the zero-arg bulk readers (so anything
// enumerating the whole table sees it).
//
// CKF Data Dump will NOT show a cloned row. It captures rows in a GetRow*
// postfix, and a synthetic row is appended to the reader's result after every
// GetRow* call has already returned, so it never passes that hook. The log is
// the place to confirm a clone: "RowClone: built ..." with its changed columns,
// then "RowClone: served ... into <reader>".
//
// WHICH LISTS IT JOINS
//
// A filtered reader returns the rows matching its arguments, and appending
// blindly would put a PL 14 squad member into a PL 2 encounter. Two tests
// decide, and both must pass ("serveOn": "auto", the default):
//
//   provenance  the list already contains the row this clone was copied from.
//               A clone of a group-1100 row appears wherever group 1100 does
//               and nowhere else, without anyone naming a column. This test
//               costs nothing and is right by construction, because the clone
//               differs from its source only where 'as' says it does.
//   gates       for the three filtered readers above, the arguments are
//               re-checked against the row's own gate columns. That is what
//               keeps a MinPowerLevel 14 member out of a PL 2 roll, which
//               provenance alone cannot do.
//
// The gate map is read off the reader's parameter names and the table's column
// names, NOT off the SQL, which is inside the encrypted database and cannot be
// read. Where a parameter has no unambiguous column — the factionId argument
// of ReadMonsterGroupMembersByGroup, against a column merely called Faction —
// it is deliberately left out of the map and provenance is trusted instead,
// since the clone carries its source's faction. "serveOn" overrides all of it:
//
//   auto        provenance and gates. The default.
//   provenance  provenance only; ignore the gate map.
//   always      append to every list this table has a reader for.
//   never       by-id only. For a row that exists purely to be pointed at.
//
// PATCHING RISK
//
// docs/patching-rules.md says patch methods that do work, never methods that
// do arithmetic, because the IL2CPP linker folds identical machine code onto
// one address and a folded detour recurses until the stack is gone. A reader
// runs a SQL statement against a distinct table name and calls a distinct
// materializer, so no two of them are identical and none is a folding
// candidate. The NativeMethodInfoPtr check below catches the lesser case of
// two interop proxies resolving to one il2cpp method; nothing managed can see
// the folding case. Nothing here is patched at all unless a clone rule names
// that table, so a rules file without "clone" adds no hooks.

using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Reflection;
using System.Text.Json;
using HarmonyLib;

namespace CKFHardMode
{
    internal static class RowClone
    {
        private sealed class CloneSpec
        {
            public Rule Rule;
            public string ModelName;      // "WeaponModel"
            public string KeyColumn;      // "WeaponId"
            public long SourceId;
            public long NewId;
            public string ServeOn;        // auto | provenance | always | never

            public Type ModelType;
            public Type HomeDb;           // the database that declares this table

            // ReadWeapon(long), per database that declares one.
            //
            // Run 34 is why this is a dictionary. WeaponModel's materializer is
            // declared on DataDb, so 2.2.1 hooked DataDb.ReadWeapon and nothing
            // else — but GameDb declares its OWN ReadWeapon(long) returning the
            // same content WeaponModel, and that is the one a mission uses. So
            // an enemy pointed at a cloned weapon reached a reader we had not
            // patched, got nothing back, and the spawn threw
            // NullReferenceException before the clone was ever built.
            //
            // A table is not owned by one database. Hook every reader that
            // returns the row, wherever it is declared.
            public readonly Dictionary<Type, MethodInfo> ByIdReaders =
                new Dictionary<Type, MethodInfo>();
            public MethodInfo ByIdReader; // the preferred one, for logging

            public object Db;             // the live database instance built from
            public MethodInfo BuiltWith;  // and the reader it was built through

            public object Template;       // the finished clone, built once
            public bool Materialized;
            public bool Broken;
            public long Served;
        }

        // model name -> the clones for it
        private static readonly Dictionary<string, List<CloneSpec>> ByModel =
            new Dictionary<string, List<CloneSpec>>(StringComparer.OrdinalIgnoreCase);

        // method key -> the clones that may apply. Built at patch time so the
        // postfix does one dictionary lookup and no reflection.
        private static readonly Dictionary<string, List<CloneSpec>> ListTargets =
            new Dictionary<string, List<CloneSpec>>(StringComparer.Ordinal);
        private static readonly Dictionary<string, List<CloneSpec>> SingleTargets =
            new Dictionary<string, List<CloneSpec>>(StringComparer.Ordinal);

        // The same specs, keyed by the id they answer to. A by-id read used to
        // scan every clone for the table looking for a matching NewId, which is
        // fine at 108 clones and is not at 1,500 — one gear ladder per armour
        // family is 770 rows on its own, and that scan runs per monster per
        // piece of gear.
        private static readonly Dictionary<string, Dictionary<long, CloneSpec>> SingleById =
            new Dictionary<string, Dictionary<long, CloneSpec>>(StringComparer.Ordinal);

        private static void IndexSingles(string key, List<CloneSpec> specs)
        {
            var byId = new Dictionary<long, CloneSpec>();
            foreach (var s in specs)
                if (!byId.ContainsKey(s.NewId)) byId[s.NewId] = s;
            SingleById[key] = byId;
        }

        private static readonly HashSet<string> Warned =
            new HashSet<string>(StringComparer.Ordinal);

        // The NEWEST instance per database, remembered as readers fire. The
        // duplicate-id check prefers the home database's reader because the
        // answers differ: DataDb.ReadWeapon returns a defaulted row for an
        // unknown id, GameDb.ReadWeapon throws — and a thrown one is logged by
        // the interop layer whatever we do with it. With 88 clones in a file
        // that is 88 alarming and meaningless exceptions at first use.
        //
        // It used to keep the FIRST instance and never replace it, which is the
        // stale-instance fault the comment on Instance() describes (Log7) left
        // on the check path after the serving path was fixed: MaterializeCore
        // reads this to ask whether a new id is free, and asking a database
        // object the game has moved on from is the read that comes back as a
        // NullReferenceException from inside the game's own reader. Every write
        // wins, so the check path and the serving path use the same rule.
        private static readonly Dictionary<Type, object> LiveDbs =
            new Dictionary<Type, object>();

        private static void Remember(MethodBase m, object instance)
        {
            var t = m?.DeclaringType;
            if (t == null || instance == null) return;
            LiveDbs[t] = instance;

            // The database objects are instance-bound with no singleton to ask,
            // so an instance can only be taken off a call the game makes.
            // ModelRules.AfterGetRow offers one too, and it is installed
            // whenever ModelRules has anything to hook; this one is only
            // installed when the rules file carries a clone rule.
            if (SelfCheck.Wants) SelfCheck.Offer(t, instance);
        }

        // Distinct (reader, arguments) shapes already reported, so the
        // diagnostic above prints once per shape rather than per call.
        private static readonly HashSet<string> ListShapes =
            new HashSet<string>(StringComparer.Ordinal);

        // Readers served by prefix. The postfix must stay out of their way.
        private static readonly HashSet<string> Prefixed =
            new HashSet<string>(StringComparer.Ordinal);


        // Materializing a clone reads its source row through the very readers
        // we have patched. Without this the first read would recurse.
        [ThreadStatic] private static bool reentrant;

        // Key() is on the by-id serving path, which a mission walks once per
        // piece of gear on every monster it restores. It used to call
        // GetParameters() — which allocates a fresh array every time — and then
        // concatenate three strings, twice per read (prefix and postfix). The
        // answer never changes for a given method, so it is worked out once.
        //
        // Replaced wholesale rather than mutated: the serving path reads this
        // without a lock and must never see a dictionary mid-resize.
        private static volatile Dictionary<MethodBase, string> keyCache =
            new Dictionary<MethodBase, string>();

        private static string Key(MethodBase m)
        {
            string k;
            if (keyCache.TryGetValue(m, out k)) return k;

            k = (m.DeclaringType == null ? "?" : m.DeclaringType.Name) + "." + m.Name
              + "/" + m.GetParameters().Length;

            lock (ByModel)
            {
                var next = new Dictionary<MethodBase, string>(keyCache);
                next[m] = k;
                keyCache = next;
            }
            return k;
        }

        // ---- setup -----------------------------------------------------------

        public static void Init(Harmony harmony, List<Rule> rules, List<Type> dbTypes)
        {
            foreach (var r in rules)
            {
                var s = Parse(r);
                if (s == null) continue;
                if (!ByModel.TryGetValue(s.ModelName, out var list))
                    ByModel[s.ModelName] = list = new List<CloneSpec>();
                list.Add(s);
            }

            if (ByModel.Count == 0) return;

            // Two clone rules on one table writing the same 'as' id. The
            // duplicate check in MaterializeCore cannot see this: it asks the
            // game's own reader, and that runs under the re-entrancy guard, so
            // clones we made ourselves are invisible to it. Left alone, both
            // rules materialize, list reads get both rows under one id, and
            // by-id reads get whichever rule happens to have loaded first.
            foreach (var kv in ByModel)
            {
                var taken = new Dictionary<long, CloneSpec>();

                // A pure scan: the loop marks a duplicate Broken and adds to
                // `taken`, and never touches kv.Value, so the copy the ToList()
                // here used to make protected nothing and only obscured that.
                foreach (var s in kv.Value)
                {
                    CloneSpec first;
                    if (taken.TryGetValue(s.NewId, out first))
                    {
                        s.Broken = true;
                        Plugin.Log.LogError($"RowClone: two rules both insert {kv.Key} "
                            + $"{s.KeyColumn} {s.NewId} — \"{first.Rule.Describe()}\" and "
                            + $"\"{s.Rule.Describe()}\". Give them different ids. The second one "
                            + "is ignored.");
                        continue;
                    }
                    taken[s.NewId] = s;
                }
            }

            // A clone of a Game* row would be a row invented inside the save.
            // Nothing here writes to the save, so it would exist only until the
            // game read the table again — and the moment it did, the game's own
            // idea of the table would disagree with ours.
            foreach (var name in ByModel.Keys.Where(
                         k => k.StartsWith("Game", StringComparison.Ordinal)).ToList())
            {
                Plugin.Log.LogWarning($"RowClone: {name} is a GameDb (save) model. Cloning is for "
                    + "shipped content, not save state; those rule(s) are ignored.");
                ByModel.Remove(name);
            }

            // Model name -> type and owning database, taken off the
            // materializer rather than TypeByName, which walks every loaded
            // assembly. First declarer wins and DataDb is scanned first, so a
            // content table resolves to DataDb.
            //
            // The home database is where the clone is ATTRIBUTED, not the only
            // place it is served. GameDb declares a ReadWeapon(long) of its own
            // returning the same content WeaponModel — the save's own weapons
            // are GameWeaponModel and come from ReadGameWeapon, a different
            // method — and a mission reads enemy gear through the GameDb one.
            // Every reader that returns the row gets hooked, wherever declared.
            var modelTypes = new Dictionary<string, Type>(StringComparer.OrdinalIgnoreCase);
            var modelHome  = new Dictionary<string, Type>(StringComparer.OrdinalIgnoreCase);
            foreach (var db in dbTypes)
                foreach (var m in AccessTools.GetDeclaredMethods(db))
                    if (m.Name.StartsWith("GetRow", StringComparison.Ordinal)
                        && m.Name.EndsWith("Model", StringComparison.Ordinal)
                        && m.ReturnType != null && !m.ReturnType.IsValueType)
                    {
                        var key = m.Name.Substring("GetRow".Length);
                        if (modelTypes.ContainsKey(key)) continue;
                        modelTypes[key] = m.ReturnType;
                        modelHome[key]  = db;
                    }

            foreach (var kv in ByModel)
            {
                Type mt;
                if (!modelTypes.TryGetValue(kv.Key, out mt))
                {
                    Plugin.Log.LogWarning($"RowClone: no materializer for {kv.Key}, so its type "
                        + "cannot be resolved and its clone rule(s) will do nothing. Check the "
                        + "spelling against _coverage.csv from the CKF Data Dump plugin.");
                    foreach (var s in kv.Value) s.Broken = true;
                    continue;
                }
                foreach (var s in kv.Value) { s.ModelType = mt; s.HomeDb = modelHome[kv.Key]; }
            }

            var thrown    = new HarmonyMethod(AccessTools.Method(typeof(RowClone), nameof(ReaderThrew)));
            var listPf    = new HarmonyMethod(AccessTools.Method(typeof(RowClone), nameof(AfterListRead)));
            var singlePf  = new HarmonyMethod(AccessTools.Method(typeof(RowClone), nameof(AfterSingleRead)));
            var singlePre = new HarmonyMethod(AccessTools.Method(typeof(RowClone), nameof(BeforeSingleRead)));

            int singles = 0;

            foreach (var db in dbTypes)
            {
                foreach (var m in AccessTools.GetDeclaredMethods(db))
                {
                    if (m.IsAbstract || m.ReturnType == null) continue;
                    if (!m.Name.StartsWith("Read", StringComparison.Ordinal)) continue;

                    var element = ElementType(m.ReturnType);      // null when not a List<T>
                    var specs = element != null
                        ? SpecsFor(element, db)
                        : SpecsFor(m.ReturnType, db);
                    if (specs == null) continue;

                    var ps = m.GetParameters();
                    var byId = element == null && ps.Length == 1 && IsInteger(ps[0]);

                    // Do not serve into a whole-table read.
                    //
                    // Run 42: a CKF Data Dump sweep called ReadArmors(), our
                    // postfix appended sixty clones to the list it returned, and
                    // from then on the mission never called ReadArmor(id) for
                    // any of them — it resolved armour from something the game
                    // had already built out of that list. The clones were not in
                    // it, because the append happens after the reader returns.
                    // The mission then died on a null armour.
                    //
                    // Nothing during play enumerates a whole table, so appending
                    // there buys nothing and can only poison whatever the game
                    // builds from it. Clones are found by id and through the
                    // filtered readers, which take arguments.
                    if (element != null && ps.Length == 0) continue;

                    // Anything else returning a bare row - ReadMonsterTypeByContactId
                    // takes a string - is not a lookup a clone can answer.
                    if (element == null && !byId) continue;

                    // The by-id reader is how a clone is built, so it has to be
                    // found whether or not it is patched. Prefer the exact name.
                    if (byId)
                        foreach (var s in specs)
                        {
                            // One per database. Within a database, the exactly
                            // named reader wins - ReadWeapon over anything else
                            // that happens to take an id and return a row.
                            MethodInfo held;
                            var exact = "Read" + Strip(s.ModelName);
                            if (!s.ByIdReaders.TryGetValue(db, out held)
                                || (m.Name == exact && held.Name != exact))
                                s.ByIdReaders[db] = m;

                            if (s.ByIdReader == null
                                || (m.Name == exact && s.ByIdReader.Name != exact
                                    && db == s.HomeDb))
                                s.ByIdReader = m;
                        }


                    string owner;
                    if (AlreadyClaimed(m, out owner))
                    {
                        Plugin.Log.LogWarning($"RowClone: {Key(m)} shares an il2cpp method with "
                            + $"{owner}; not patching it. Clones of {specs[0].ModelName} will not "
                            + "appear there.");
                        continue;
                    }

                    try
                    {
                        if (element != null)
                        {
                            harmony.Patch(m, postfix: listPf);
                            ListTargets[Key(m)] = specs;
                        }
                        else
                        {
                            // PREFIX, not postfix. Run 35: GameDb.ReadWeapon
                            // does not answer an unknown id with an empty row
                            // the way DataDb.ReadWeapon does — it throws
                            // NullReferenceException inside the game. A postfix
                            // still supplied the clone and the mission loaded,
                            // but every serve left a logged exception behind and
                            // depended on the interop layer swallowing it. A
                            // prefix answers before the game's lookup runs, so
                            // the throwing path is never entered.
                            bool serves = false;
                            try
                            {
                                harmony.Patch(m, prefix: singlePre);
                                Prefixed.Add(Key(m));
                                serves = true;
                            }
                            catch (Exception e)
                            {
                                Plugin.Log.LogWarning($"RowClone: {Key(m)} would not take a "
                                    + $"prefix ({e.GetType().Name}), falling back to the postfix "
                                    + "for serving too. Serving still works; expect a logged "
                                    + "exception per serve if this reader throws on an unknown "
                                    + "id.");
                            }

                            // The postfix goes on EITHER WAY, and it used to go
                            // on only in the catch above. It carries MissCheck —
                            // the exact dangling-reference check, and the only
                            // one that can be exact, because the game has just
                            // answered — so on every reader whose prefix took
                            // (the normal case) that check never ran at all.
                            // Harmony runs a postfix even when a prefix returned
                            // false, so it sees the clone the prefix supplied and
                            // MissCheck reads that as "the row is there", which
                            // is correct. `Prefixed` is what tells it not to
                            // serve a second time.
                            try { harmony.Patch(m, postfix: singlePf); serves = true; }
                            catch (Exception e)
                            {
                                Plugin.Log.LogWarning($"RowClone: {Key(m)} would not take a "
                                    + $"postfix ({e.GetType().Name}), so a row pointing at an id "
                                    + "this reader cannot resolve will not be named here."
                                    + (serves ? "" : " Nor can clones be served on it: neither "
                                        + "patch took."));
                            }

                            // Whatever shape the serving patch took, the
                            // finalizer goes on too: it is the only thing that
                            // sees a reader die on an id.
                            try { harmony.Patch(m, finalizer: thrown); }
                            catch (Exception e)
                            {
                                Plugin.Log.LogWarning($"RowClone: {Key(m)} would not take a "
                                    + $"finalizer ({e.GetType().Name}); a reader that throws "
                                    + "there will not name its id.");
                            }

                            SingleTargets[Key(m)] = specs;
                            IndexSingles(Key(m), specs);

                            // Only a reader that can actually answer counts
                            // towards "some by-id reader was patched"; the
                            // finalizer and the id index above are registered
                            // either way, because ReaderThrew still names the id
                            // on a reader neither patch took.
                            if (serves) singles++;
                        }
                        Claim(m);
                    }
                    catch (Exception e)
                    {
                        Plugin.Log.LogWarning($"RowClone: could not hook {Key(m)}: {e.Message}");
                    }
                }
            }

            foreach (var kv in ByModel)
                foreach (var s in kv.Value)
                {
                    if (s.Broken) continue;
                    if (s.ByIdReader == null || s.ByIdReaders.Count == 0)
                    {
                        s.Broken = true;
                        Plugin.Log.LogWarning($"RowClone: {kv.Key} has no single-row by-id reader, "
                            + "so there is no way to fetch the source row. "
                            + $"\"{s.Rule.Describe()}\" is ignored.");
                        continue;
                    }
                }

            if (singles == 0)
                Plugin.Log.LogWarning("RowClone: no by-id reader was patched, so nothing can point "
                    + "at a cloned row by id.");
        }

        // A rule that points a row at a clone that will not exist.
        //
        // This is the shape that killed Run 34: MonsterTypeModel rows had their
        // WeaponTypeId set to 20020, the clone was never served, and the game
        // threw NullReferenceException spawning a monster holding a weapon it
        // could not find. A dangling reference does not degrade — it stops the
        // mission loading — so it is worth an error at load rather than a
        // surprise thirty minutes in.
        //
        // Matched on the VALUE alone, across models: a rule setting any column
        // to 20020 is treated as pointing at the WeaponModel clone 20020. Clone
        // ids are chosen to be unused, so a collision with an unrelated setting
        // is unlikely, and over-reporting here is much cheaper than silence.
        internal static void WarnAboutDanglingReferences(IEnumerable<Rule> rules)
        {
            // Every id a clone rule declares, whether or not it survived.
            var declared = new HashSet<long>();
            var missing = new Dictionary<long, string>();
            foreach (var kv in ByModel)
                foreach (var s in kv.Value)
                {
                    declared.Add(s.NewId);
                    if (s.Broken && !missing.ContainsKey(s.NewId))
                        missing[s.NewId] = kv.Key + " " + s.KeyColumn + " " + s.NewId;
                }

            foreach (var rule in rules)
            {
                if (rule.IsClone) continue;
                CheckLiterals(rule, missing, declared);
                CheckCurves(rule, missing, declared);
            }
        }

        // A rule that points at a clone which was refused, or disabled.
        private static void CheckLiterals(Rule rule, Dictionary<long, string> missing,
                                          HashSet<long> declared)
        {
            if (rule.Set == null) return;
            foreach (var kv in rule.Set)
            {
                if (kv.Value.ValueKind != JsonValueKind.Number) continue;
                double d;
                try { d = kv.Value.GetDouble(); } catch { continue; }
                var id = (long)d;
                if (id != d) continue;

                string what;
                if (missing.TryGetValue(id, out what))
                {
                    Plugin.Log.LogError($"RowClone: \"{rule.Describe()}\" sets "
                        + $"{rule.Model}.{kv.Key} = {id}, but {what} "
                        + "was not created. Nothing will resolve that id — expect the "
                        + "mission not to load.");
                    continue;
                }

                // An id in the range this project reserves for clones, that no
                // clone rule declares, is a typo by construction: the game does
                // not ship rows up there.
                if (id >= ReservedFrom && !declared.Contains(id))
                    Plugin.Log.LogError($"RowClone: \"{rule.Describe()}\" sets "
                        + $"{rule.Model}.{kv.Key} = {id}, which is in the reserved range "
                        + $"({ReservedFrom}+) but no clone rule creates it. Nothing will resolve "
                        + "that id — expect the mission not to load.");
            }
        }

        // A pointer curve is only checkable where an id cannot possibly be a
        // shipped row: the reserved range. Anywhere else, a value this rule
        // produces might be a real row the developers ship, and nothing at load
        // can tell the difference — the table cannot be enumerated without
        // forcing a read that has its own consequences.
        //
        // AND IT CANNOT KNOW HOW HIGH THE LEVEL GOES. An earlier version swept a
        // guessed level range and compared against declared clone ids; it
        // reported twelve faults in a config with none, because a curve keyed on
        // PowerLevel does not know that power levels stop at 20. Restricting it
        // to the reserved range did not fix that — it only moved it. A ladder of
        // twenty tiers based at 901000 runs out at level 21, and a sweep that
        // keeps going reports 901040 as missing. It is missing. No row will ever
        // ask for it. Log7 carried five of these against a config with none, and
        // an error channel that cries wolf is worse than no error channel.
        //
        // So this says WHEN the ladder runs out and leaves the judgement to
        // whoever knows the data. It is a warning, not an error, and the real
        // check is offline in scripts/validate_rules.py, which reads the dump
        // and knows the actual PowerLevel of every row in every PowerGroup.
        // The other exact check is at serve time, in AfterSingleRead and
        // ReaderThrew: the game itself says whether a row exists.
        //
        // `missing` is the same map CheckLiterals uses, and for the same
        // reason: a clone rule that was REFUSED still put its id in `declared`,
        // so a curve landing on a broken clone's id used to be accepted while
        // the identical literal set was an error. One rule for both — an id
        // counts as covered only when a clone rule declares it AND that rule
        // survived load.
        private static void CheckCurves(Rule rule, Dictionary<long, string> missing,
                                        HashSet<long> declared)
        {
            if (rule.SetTerms == null) return;

            foreach (var term in rule.SetTerms)
            {
                if (!term.Column.EndsWith("Id", StringComparison.Ordinal)) continue;

                // Where does the ladder stop? The last level whose id a clone
                // rule (or a shipped row below the reserved range) covers.
                double lastGood = double.NaN;
                for (var level = term.Threshold; level <= term.Threshold + 64; level += 1.0)
                {
                    var v = ModelRules.EvaluateAt(term, level);
                    var id = (long)Math.Round(v);
                    if (Math.Abs(v - id) > 1e-6) continue;

                    if (id < ReservedFrom
                        || (declared.Contains(id) && !missing.ContainsKey(id)))
                    { lastGood = level; continue; }

                    var column = string.IsNullOrEmpty(term.LevelColumn)
                               ? "PowerLevel" : term.LevelColumn;

                    // lastGood stays NaN when the very first level the term
                    // covers is already past the end — which is what a constant
                    // set of a reserved id looks like, since it has no ladder at
                    // all. Say that rather than printing "above PowerLevel NaN".
                    var where = double.IsNaN(lastGood)
                              ? "covers no usable id at all"
                              : $"runs out of ladder above {column} {lastGood:0}";

                    if (Warned.Add("ladder|" + rule.Index + "|" + term.Column))
                        Plugin.Log.LogWarning($"RowClone: \"{rule.Describe()}\" {where}: "
                            + $"at {column} {level:0} it would "
                            + $"set {rule.Model}.{term.Column} = {id}, and "
                            + (missing.ContainsKey(id)
                                ? "the clone rule that would create that row was refused at load"
                                : "nothing creates that row")
                            + ". Harmless if no row of that table ever reaches "
                            + $"{column} {level:0} — which is the usual case, and is why this is "
                            + "not an error. scripts/validate_rules.py settles it against the "
                            + "dump.");
                    break;   // one line per term is enough to find it
                }
            }
        }

        private const long ReservedFrom = 900000;

        private static List<CloneSpec> SpecsFor(Type modelType, Type db)
        {
            if (modelType == null) return null;
            List<CloneSpec> hit = null;
            foreach (var kv in ByModel)
                foreach (var s in kv.Value)
                    // Deliberately NOT filtered by database. See CloneSpec.ByIdReaders.
                    if (s.ModelType == modelType && !s.Broken)
                        (hit ??= new List<CloneSpec>()).Add(s);
            return hit;
        }

        private static string Strip(string modelName) =>
            modelName.EndsWith("Model", StringComparison.Ordinal)
                ? modelName.Substring(0, modelName.Length - "Model".Length)
                : modelName;

        private static bool IsInteger(ParameterInfo p)
        {
            var t = Nullable.GetUnderlyingType(p.ParameterType) ?? p.ParameterType;
            return t == typeof(long) || t == typeof(int) || t == typeof(short) || t == typeof(uint);
        }

        // Il2CppSystem.Collections.Generic.List<T> -> T, otherwise null.
        private static Type ElementType(Type t)
        {
            try
            {
                if (!t.IsGenericType) return null;
                if (t.Name.IndexOf("List", StringComparison.Ordinal) < 0) return null;
                var args = t.GetGenericArguments();
                return args.Length == 1 ? args[0] : null;
            }
            catch { return null; }
        }

        private static CloneSpec Parse(Rule r)
        {
            if (r.Clone.Count != 1)
            {
                Plugin.Log.LogWarning($"RowClone: \"{r.Describe()}\" — 'clone' must name exactly "
                    + "one column and its value, the id of the row to copy. Skipped.");
                return null;
            }
            var src = r.Clone.First();
            if (src.Value.ValueKind != JsonValueKind.Number)
            {
                Plugin.Log.LogWarning($"RowClone: \"{r.Describe()}\" — 'clone.{src.Key}' must be a "
                    + "number. Skipped.");
                return null;
            }
            if (r.As == null || !r.As.TryGetValue(src.Key, out var newId)
                || newId.ValueKind != JsonValueKind.Number)
            {
                Plugin.Log.LogWarning($"RowClone: \"{r.Describe()}\" — 'as' must give the new row a "
                    + $"'{src.Key}'. A clone without its own id would collide with the row it was "
                    + "copied from. Skipped.");
                return null;
            }

            if (r.Where != null || r.WhereMin != null || r.WhereMax != null)
                Plugin.Log.LogWarning($"RowClone: \"{r.Describe()}\" is a clone rule, so its "
                    + "where/whereMin/whereMax select nothing — 'clone' already names the one row "
                    + "being copied. The selectors are ignored.");

            var serve = (r.ServeOn ?? "auto").Trim().ToLowerInvariant();
            if (serve != "auto" && serve != "provenance" && serve != "always" && serve != "never")
            {
                Plugin.Log.LogWarning($"RowClone: \"{r.Describe()}\" — serveOn '{r.ServeOn}' is not "
                    + "one of auto, provenance, always, never. Using auto.");
                serve = "auto";
            }

            return new CloneSpec
            {
                Rule = r,
                ModelName = r.Model,
                KeyColumn = src.Key,
                SourceId = (long)src.Value.GetDouble(),
                NewId = (long)newId.GetDouble(),
                ServeOn = serve,
            };
        }

        // ---- building the row ------------------------------------------------

        private static object Build(CloneSpec s, object db, MethodInfo reader)
        {
            object row;
            reentrant = true;
            try { row = reader.Invoke(reader.IsStatic ? null : db,
                                      new object[] { s.SourceId }); }
            catch (Exception e)
            {
                var inner = e.InnerException ?? e;
                Plugin.Log.LogWarning($"RowClone: reading {s.ModelName} {s.KeyColumn} {s.SourceId} "
                    + $"threw {inner.GetType().Name}: {inner.Message}");
                return null;
            }
            finally { reentrant = false; }

            if (row == null) return null;

            // 'as' first: it carries the new id, and an operation below may want
            // to slope off a column 'as' has just set.
            ModelRules.Assign(row, row.GetType(), s.Rule.As, "as");
            ModelRules.Apply(row, s.Rule);
            return row;
        }

        // `dbType` is the database the hooked reader was declared on, which is
        // what decides which by-id reader can be called with `db`.
        private static void Materialize(CloneSpec s, object db, Type dbType)
        {
            if (s.Materialized || s.Broken) return;

            var reader = ReaderFor(s, dbType);
            if (reader == null) return;          // this database cannot fetch the row
            if (db == null && !reader.IsStatic) return;   // no live database yet

            // Anything that goes wrong in here is permanent — a missing source
            // row, a column 'as' cannot convert. Without this the spec would sit
            // at neither Materialized nor Broken and every later read would
            // retry it, which costs two database reads and a thrown exception
            // per reader call for the rest of the session.
            try { MaterializeCore(s, db, reader); }
            catch (Exception e)
            {
                s.Broken = true;
                var inner = e.InnerException ?? e;
                Plugin.Log.LogError($"RowClone: building {s.ModelName} {s.KeyColumn} {s.NewId} "
                    + $"threw {inner.GetType().Name}: {inner.Message}. "
                    + $"\"{s.Rule.Describe()}\" is ignored.");
            }
        }

        // The by-id reader this spec can use through `dbType`, or null. A clone
        // can be built through ANY database that reads the row — the row is the
        // same either way — so whichever reader we are already inside is used.
        private static MethodInfo ReaderFor(CloneSpec s, Type dbType)
        {
            MethodInfo r;
            if (dbType != null && s.ByIdReaders.TryGetValue(dbType, out r)) return r;
            return null;
        }

        private static void MaterializeCore(CloneSpec s, object db, MethodInfo reader)
        {
            s.Db = db;
            s.BuiltWith = reader;

            // 1. Fetch the row being copied.
            //
            // This has to come first. The by-id reader looks up the table's
            // PRIMARY id whatever column 'clone' happens to name, so until this
            // read has been checked against that column, nothing else here is
            // meaningful — a duplicate-id check against the wrong column would
            // report a collision that is not the actual fault.
            object source = null;
            Exception failure = null;
            reentrant = true;
            try { source = reader.Invoke(reader.IsStatic ? null : db,
                                         new object[] { s.SourceId }); }
            catch (Exception e) { failure = e.InnerException ?? e; }
            finally { reentrant = false; }

            if (failure != null)
            {
                s.Broken = true;
                Plugin.Log.LogError($"RowClone: reading {s.ModelName} {s.KeyColumn} {s.SourceId} "
                    + $"threw {failure.GetType().Name}: {failure.Message}. "
                    + $"\"{s.Rule.Describe()}\" is ignored.");
                return;
            }
            if (source == null)
            {
                s.Broken = true;
                Plugin.Log.LogError($"RowClone: {s.ModelName} {s.KeyColumn} {s.SourceId} — the row "
                    + $"being copied does not exist. \"{s.Rule.Describe()}\" is ignored.");
                return;
            }

            // 2. Confirm 'clone' named the column the reader keys on.
            //
            //    This also catches a row that came back for an id the table does
            //    not hold — the reader returns a live object with every column
            //    defaulted rather than null, so a key that is not SourceId means
            //    "no such row" just as much as it means "wrong column".
            //
            // {"clone": {"PowerLevel": 10}} on WeaponModel would otherwise
            // silently clone WeaponId 10 — a low-numbered player weapon — and
            // nothing downstream would notice.
            var keyProp = ModelRules.Prop(source.GetType(), s.KeyColumn);
            var keyValue = keyProp == null ? null : keyProp.GetValue(source);
            long keyAsLong = 0;
            bool keyReadable = false;
            if (keyValue != null)
            {
                try
                {
                    keyAsLong = Convert.ToInt64(keyValue, CultureInfo.InvariantCulture);
                    keyReadable = true;
                }
                catch { }
            }
            if (!keyReadable || keyAsLong != s.SourceId)
            {
                s.Broken = true;
                var seen = keyValue == null ? "absent" : keyValue.ToString();

                // A defaulted key is the table saying it has no such row. A
                // populated one that disagrees means 'clone' named the wrong
                // column and the reader looked up something else entirely.
                var diagnosis = (keyReadable && keyAsLong == 0)
                    ? $"{s.ModelName} has no row with {s.KeyColumn} {s.SourceId} — the reader "
                      + "returned an empty row, which is how this table reports a miss"
                    : $"'clone' has to name the id column {reader.Name} looks rows up by, "
                      + $"and {s.ModelName}.{s.KeyColumn} is not it — asking for {s.SourceId} "
                      + $"returned a row whose {s.KeyColumn} is {seen}";

                Plugin.Log.LogError($"RowClone: {diagnosis}. "
                    + $"\"{s.Rule.Describe()}\" is ignored.");
                return;
            }

            // 3. Refuse an id the table already uses. Serving a second row under
            //    an existing id makes which one you get a matter of call order.
            //    A reader's answer for an id the table does not hold is not
            //    uniform — DataDb.ReadWeapon returns a defaulted row, GameDb's
            //    throws — so this check trips the game's own error path on a
            //    FREE id. That is expected and handled; say so, because an
            //    unexplained NullReferenceException in the log at this exact
            //    point is exactly what a real fault looks like.
            //    Prefer the home database, which answers a miss quietly.
            var checkReader = reader;
            var checkDb = db;
            MethodInfo homeReader;
            object homeDb;
            if (s.HomeDb != null
                && s.ByIdReaders.TryGetValue(s.HomeDb, out homeReader)
                && LiveDbs.TryGetValue(s.HomeDb, out homeDb))
            { checkReader = homeReader; checkDb = homeDb; }

            if (Warned.Add("check|" + s.ModelName))
                Plugin.Log.LogInfo($"RowClone: checking each new {s.ModelName} id is unused via "
                    + $"{checkReader.DeclaringType?.Name}.{checkReader.Name}. If the game logs a "
                    + "NullReferenceException from it, that is this check finding an id free, and "
                    + "it is handled. Reported once per table.");

            //    Through ReadById, so an empty row does not read as a taken id.
            //    Checking non-null alone was the 2.2.0 bug: every by-id reader
            //    answers a miss with a defaulted object, so EVERY clone was
            //    refused for colliding with a row that did not exist.
            if (ReadById(checkReader, checkDb, s.NewId, s.KeyColumn) != null)
            {
                s.Broken = true;
                Plugin.Log.LogError($"RowClone: {s.ModelName} {s.KeyColumn} {s.NewId} already "
                    + $"exists, so \"{s.Rule.Describe()}\" would give one id two rows. Pick an "
                    + "unused id. Nothing was inserted.");
                return;
            }

            // 4. The row from step 1 is private to us and already carries every
            //    column, so it becomes the clone directly rather than costing a
            //    third read.
            //
            //    Snapshot first: a clone is built once per session, so printing
            //    what actually moved costs nothing and is the only proof that
            //    the 'as' block and the operations landed. CKF Data Dump cannot
            //    show a synthetic row — see the note at the top of this file.
            var before = ModelRules.Snapshot(source, ModelRules.Touched(s.Rule));

            ModelRules.Assign(source, source.GetType(), s.Rule.As, "as");
            ModelRules.Apply(source, s.Rule);

            s.Template = source;
            s.Materialized = true;

            var changes = ModelRules.Changes(source, before);
            Plugin.Log.LogInfo($"RowClone: built {s.ModelName} {s.KeyColumn} {s.NewId} "
                             + $"from {s.SourceId} — "
                             + (changes.Length > 0 ? changes : "no column changed, which means "
                                 + "'as' and the operations named nothing writable"));
        }

        // A by-id reader does NOT return null for an id the table does not hold.
        // Run32 established that: ReadWeapon(20020) came back as a live object
        // with every column at its default, and the collision check read that as
        // "the id is taken" and refused a clone of an id nothing was using.
        //
        // So a row counts as found only when its key column actually carries the
        // id that was asked for. Everything that reads by id goes through here.
        private static object ReadById(MethodInfo reader, object db, long id, string keyColumn)
        {
            object row;
            reentrant = true;
            try { row = reader.Invoke(reader.IsStatic ? null : db, new object[] { id }); }
            catch { return null; }          // a throw is not evidence either way
            finally { reentrant = false; }

            return KeyOf(row, keyColumn) == id ? row : null;
        }

        // The row's key as a long, or long.MinValue when it has none to read.
        private static long KeyOf(object row, string keyColumn)
        {
            if (row == null) return long.MinValue;
            var p = ModelRules.Prop(row.GetType(), keyColumn);
            if (p == null) return long.MinValue;
            try
            {
                var v = p.GetValue(row);
                if (v == null) return long.MinValue;
                return Convert.ToInt64(v, CultureInfo.InvariantCulture);
            }
            catch { return long.MinValue; }
        }

        // A fresh copy per read, the way the game re-materializes a real row —
        // WHEN IT CAN. There is no "shared-instance mode" and no toggle; an
        // earlier comment here described one, and it does not exist.
        //
        // What does exist is the fallback below: with no usable reader, or when
        // rebuilding fails on every reader, this hands back s.Template — the one
        // object built at materialize time — and every caller that lands on that
        // path gets the SAME object. Anything the game writes onto a served
        // template therefore survives into the next serve, and GatesPass and
        // Gates read s.Template directly, so it also changes later gating
        // decisions. Nothing here can prevent that: the alternative to handing
        // back the template is handing back nothing.
        //
        // THE INSTANCE MATTERS. Building a copy means re-reading the source row
        // through a database object, and this used to always use `s.Db` — the
        // instance captured the first time the clone was materialized, held for
        // the rest of the session. That is fine as long as clones materialize
        // during the mission that uses them, which is what lazy building
        // guarantees and what every run up to Run 43 did.
        //
        // It stops being fine the moment something builds a clone EARLIER, as
        // [SelfCheck] does: the instance that existed then gets pinned, and
        // every later serve re-reads through it. If the game has moved on to a
        // different database object since, that read goes into a stale one, and
        // what comes back is the game's own NullReferenceException from inside
        // ReadWeapon — with no id in it, and a mission that never finishes
        // loading. Log7.
        //
        // So the live instance wins. Every serving hook already has it: it is
        // the `__instance` of the very call we are answering. The captured pair
        // is the fallback for a path that does not carry one.
        private static object Instance(CloneSpec s, object liveDb, Type liveDbType)
        {


            var db = s.Db;
            var reader = s.BuiltWith;

            MethodInfo live;
            if (liveDb != null && liveDbType != null
                && s.ByIdReaders.TryGetValue(liveDbType, out live))
            {
                db = liveDb;
                reader = live;
            }

            if (reader == null) return s.Template;

            var row = Build(s, db, reader);
            if (row != null) return row;

            // The live reader refused. If that was not the pair the clone was
            // built with, try that one before giving up — but say so, because a
            // reader that cannot re-read a source row it read once is the
            // symptom the comment above describes.
            if (!ReferenceEquals(reader, s.BuiltWith) && s.BuiltWith != null)
            {
                if (Warned.Add("stale|" + s.ModelName + "|" + s.NewId))
                    Plugin.Log.LogWarning($"RowClone: re-reading {s.ModelName} {s.KeyColumn} "
                        + $"{s.SourceId} through the live {liveDbType?.Name} failed; falling back "
                        + "to the database this clone was built with. Reported once per clone.");
                row = Build(s, s.Db, s.BuiltWith);
            }
            return row ?? s.Template;
        }

        // ---- serving ---------------------------------------------------------

        public static void AfterListRead(MethodBase __originalMethod, object __instance,
                                         object[] __args, object __result)
        {
            // ModelRules.Halted is the shared kill switch a partial ModelRules
            // init sets: with it on, nothing this file installed does anything,
            // so the game runs unmodified rather than half-modified.
            if (ModelRules.Halted || reentrant || __result == null) return;
            Remember(__originalMethod, __instance);

            List<CloneSpec> specs;
            if (!ListTargets.TryGetValue(Key(__originalMethod), out specs)) return;

            try
            {
                var shape = ListShape.For(__result.GetType());
                if (shape == null || !shape.CanAdd) return;

                // Why a clone was or was not offered, per spec. Only assembled
                // when tracing is on — this runs on a reader the game calls.
                var diagnose = ModelRules.TraceLimit > 0;
                List<string> why = diagnose ? new List<string>() : null;

                // The provenance test — is the row this was copied from already
                // in this list? — used to walk the whole list once PER CLONE.
                // The list is the same for all of them, so walk it once and
                // answer everyone from the set. Built lazily, because a reader
                // whose clones are all gated out should not pay for it at all.
                //
                // It is also kept up to date as clones are appended below. It
                // used to hold only what the reader returned, so a clone whose
                // SourceId is another clone's NewId could never pass provenance:
                // the earlier clone had been appended to the list, but not to
                // the set the test reads. Chained clones vanished from every
                // filtered read while working fine by id.
                HashSet<long> present = null;
                string presentFor = null;

                foreach (var s in specs)
                {
                    if (s.Broken) { why?.Add($"{s.NewId}: rule was refused at load"); continue; }
                    if (s.ServeOn == "never") { why?.Add($"{s.NewId}: serveOn=never"); continue; }

                    // Provenance BEFORE materializing. Nothing here needs the
                    // built row, and building every clone for a table on any
                    // list read is what made a large file expensive — a mission
                    // should only ever build the tiers it actually reaches.
                    if (s.ServeOn != "always")
                    {
                        if (!shape.Usable) { why?.Add($"{s.NewId}: list has no indexer"); continue; }

                        if (present == null || presentFor != s.KeyColumn)
                        {
                            present = shape.ColumnValues(__result, s.KeyColumn);
                            presentFor = s.KeyColumn;
                        }

                        // The list already holds this id — a cached list, or a
                        // second pass over the same one. Appending again would
                        // put two rows under one id into it, which is the state
                        // MaterializeCore refuses at build time. serveOn=always
                        // skips the list scan entirely and so cannot be checked
                        // this way.
                        if (present.Contains(s.NewId))
                        { why?.Add($"{s.NewId}: already in this list"); continue; }

                        if (!present.Contains(s.SourceId))
                        {
                            // Gates() reads the built row, so with tracing on
                            // build it just to say what its gate columns hold.
                            if (diagnose) Materialize(s, __instance,
                                                      __originalMethod.DeclaringType);

                            // Naming the clone's own gate columns here turns a
                            // dead end into an answer. Run 37: every clone was
                            // rejected this way, and the reason was that the
                            // chosen source rows were themselves gated out of a
                            // PL 18 call — MaxPowerLevel 5 filler entries. The
                            // engine was right; the rules picked bad sources.
                            why?.Add($"{s.NewId}: source row {s.SourceId} is not in this list"
                                   + Gates(s));
                            continue;
                        }
                    }

                    Materialize(s, __instance, __originalMethod.DeclaringType);
                    if (!s.Materialized) { why?.Add($"{s.NewId}: not built yet"); continue; }

                    if (s.ServeOn == "auto" && !GatesPass(s, __originalMethod, __args))
                    { why?.Add($"{s.NewId}: a gate on the arguments rejected it"); continue; }

                    var row = Instance(s, __instance, __originalMethod.DeclaringType);
                    if (row == null) { why?.Add($"{s.NewId}: could not materialize a row"); continue; }
                    if (!shape.Add(__result, row))
                    { why?.Add($"{s.NewId}: the list refused the row"); continue; }

                    // The list has it now, so the provenance set has it too: a
                    // later spec cloning THIS row finds its source, and nothing
                    // appends it twice.
                    if (present != null && presentFor == s.KeyColumn) present.Add(s.NewId);

                    s.Served++;
                    why?.Add($"{s.NewId}: SERVED");

                    if (s.Served <= 3)
                        Plugin.Log.LogInfo($"RowClone: served {s.ModelName} {s.KeyColumn} {s.NewId} "
                                         + $"into {__originalMethod.Name}"
                                         + $"({Args(__args)})"
                                         + (s.Served == 3 ? "  (further hits are not logged)" : ""));
                }

                // One line per distinct call shape. This is how you find out
                // which groups a mission actually asks for — the arguments are
                // not otherwise visible anywhere — and why a clone that looked
                // correct did not appear.
                if (diagnose)
                {
                    var callShape = Key(__originalMethod) + "(" + Args(__args) + ")";
                    if (ListShapes.Count < 60 && ListShapes.Add(callShape))
                    {
                        var n = shape.Count(__result);

                        // Most rejections on a given call are clones belonging to
                        // some other group, and printing a gate breakdown for each
                        // buries the one line that matters. Served first, then two
                        // rejections in full, then a count.
                        var served = why.Where(x => x.EndsWith("SERVED", StringComparison.Ordinal))
                                        .ToList();
                        var refused = why.Where(x => !x.EndsWith("SERVED", StringComparison.Ordinal))
                                         .ToList();
                        var shown = served.Concat(refused.Take(2)).ToList();
                        if (refused.Count > 2)
                            shown.Add($"+{refused.Count - 2} more not in this list");

                        Plugin.Log.LogInfo($"  RowClone list: {__originalMethod.Name}({Args(__args)})"
                            + $" returned {n} row(s) — " + string.Join("; ", shown));
                    }
                }
            }
            catch (Exception e) { Complain(__originalMethod, e); }
        }

        // A by-id read for an id we hold a clone under, answered BEFORE the
        // game looks. Returning false skips the original entirely.
        //
        // This is the serving path that matters. The game's own lookup for an id
        // its table does not hold is not uniform: DataDb.ReadWeapon returns a
        // row with every column defaulted, GameDb.ReadWeapon throws. Neither is
        // something to build on, so the clone is supplied without asking.
        public static bool BeforeSingleRead(MethodBase __originalMethod, object __instance,
                                            object[] __args, ref object __result)
        {
            if (ModelRules.Halted || reentrant) return true;
            Remember(__originalMethod, __instance);

            Dictionary<long, CloneSpec> byId;
            if (!SingleById.TryGetValue(Key(__originalMethod), out byId)) return true;
            if (__args == null || __args.Length != 1 || __args[0] == null) return true;

            try
            {
                long asked;
                try { asked = Convert.ToInt64(__args[0], CultureInfo.InvariantCulture); }
                catch { return true; }

                CloneSpec s;
                if (byId.TryGetValue(asked, out s) && !s.Broken)
                {
                    Materialize(s, __instance, __originalMethod.DeclaringType);
                    if (!s.Materialized) return true;

                    var row = Instance(s, __instance, __originalMethod.DeclaringType);
                    if (row == null) return true;

                    __result = row;
                    s.Served++;
                    if (s.Served <= 3)
                        Plugin.Log.LogInfo($"RowClone: served {s.ModelName} {s.KeyColumn} "
                            + $"{s.NewId} from {__originalMethod.Name}"
                            + (s.Served == 3 ? "  (further hits are not logged)" : ""));
                    return false;      // the game never looks
                }
            }
            catch (Exception e) { Complain(__originalMethod, e); }
            return true;
        }

        // A by-id read that has just answered.
        //
        // Installed on EVERY hooked by-id reader, whether or not the prefix took
        // — it used to go on only when the prefix was refused, so on the normal
        // path MissCheck below never ran at all. It does two jobs, and which
        // ones apply depends on whether this reader also has the prefix:
        //
        //   always            MissCheck: the game has just said whether it holds
        //                     this row, and that is the only exact answer
        //                     available anywhere.
        //   prefix refused    serving, and the collision re-check that goes with
        //                     it. On a reader that HAS the prefix, the game's
        //                     lookup never ran and __result is the clone the
        //                     prefix supplied, so there is no game row here to
        //                     compare against and the collision case cannot be
        //                     seen from this side at all.
        //
        // __result is `ref object` rather than the model type because this one
        // postfix serves every table. Harmony refuses a postfix it cannot bind,
        // and a refusal throws — which is caught at patch time and logged.
        public static void AfterSingleRead(MethodBase __originalMethod, object __instance,
                                           object[] __args, ref object __result)
        {
            if (ModelRules.Halted || reentrant) return;

            var key = Key(__originalMethod);

            List<CloneSpec> specs;
            if (!SingleTargets.TryGetValue(key, out specs)) return;
            if (__args == null || __args.Length != 1 || __args[0] == null) return;

            // The exact dangling-reference check, and the only one that can be
            // exact: the game has just told us whether it holds this row.
            //
            // A by-id reader answers a miss with an object whose key column is
            // not the id asked for. If nothing served that id either, some row
            // is pointing at something that does not exist — which does not
            // degrade a stat, it stops the mission loading, and the exception
            // never reaches this log. Naming the id here is the difference
            // between a five-minute fix and a black screen.
            //
            // Where the prefix served, __result is that clone and its key column
            // carries the id, so this reads as "the row is there" — which it is.
            MissCheck(key, specs, __args[0], __result);

            // The prefix already answered this call, so __result is ours and
            // there is nothing here to serve or to compare. Not dead: `Prefixed`
            // holds every reader whose prefix took, which is now the usual case.
            if (Prefixed.Contains(key)) return;

            try
            {
                long asked;
                try { asked = Convert.ToInt64(__args[0], CultureInfo.InvariantCulture); }
                catch { return; }

                Dictionary<long, CloneSpec> byId;
                CloneSpec s;
                if (SingleById.TryGetValue(key, out byId)
                    && byId.TryGetValue(asked, out s) && !s.Broken)
                {
                    Materialize(s, __instance, __originalMethod.DeclaringType);
                    if (!s.Materialized) return;

                    // Not `__result != null`. A by-id reader answers a miss
                    // with a live object whose columns are all defaults, so the
                    // question is whether the row it handed back actually
                    // carries the id that was asked for.
                    if (KeyOf(__result, s.KeyColumn) == asked)
                    {
                        // Materialize already refuses a colliding id, so this is
                        // the game having grown a row under that id since. Leave
                        // the game's row alone and say so once.
                        if (Warned.Add("collide|" + s.ModelName + "|" + s.NewId))
                            Plugin.Log.LogWarning($"RowClone: {s.ModelName} {s.KeyColumn} "
                                + $"{s.NewId} now exists in the game's own table; the clone is "
                                + "not being served.");
                        return;
                    }

                    var row = Instance(s, __instance, __originalMethod.DeclaringType);
                    if (row == null) return;
                    __result = row;
                    s.Served++;
                    if (s.Served <= 3)
                        Plugin.Log.LogInfo($"RowClone: served {s.ModelName} {s.KeyColumn} "
                            + $"{s.NewId} from {__originalMethod.Name}"
                            + (s.Served == 3 ? "  (further hits are not logged)" : ""));
                    return;
                }
            }
            catch (Exception e) { Complain(__originalMethod, e); }
        }

        // A by-id reader that THREW rather than returned.
        //
        // MissCheck cannot see this case and never could: it lives in a
        // postfix, and Harmony does not run a postfix when the original throws.
        // So the loudest possible failure — the game's own reader dying on an
        // id — was the quietest thing in the log. All you got was an
        // Il2CppInterop trampoline dump with no id in it, and then the mission
        // hung.
        //
        // A finalizer runs either way. This one only reports: it hands the
        // exception straight back, because suppressing it would return null to
        // a caller that is about to dereference it, which trades a named
        // failure for an unnamed one.
        public static Exception ReaderThrew(Exception __exception, MethodBase __originalMethod,
                                            object[] __args)
        {
            if (__exception == null) return null;

            // Halted: report nothing, but hand the exception straight back.
            // Returning null from a finalizer SUPPRESSES it, which is the one
            // thing this method must never do — see the note above.
            if (ModelRules.Halted) return __exception;
            try
            {
                var key = Key(__originalMethod);
                var id = __args != null && __args.Length == 1 && __args[0] != null
                       ? Convert.ToString(__args[0], CultureInfo.InvariantCulture) : "?";

                // Materializing a clone asks the game for an id it does not
                // hold on purpose — that is the duplicate-id check, and it is
                // expected to throw on some databases. Not news.
                if (reentrant)
                {
                    if (Warned.Add("threw-check|" + key))
                        Plugin.Log.LogInfo($"RowClone: {key}({id}) threw during the duplicate-id "
                            + "check, which is that check finding the id free. Handled.");
                    return __exception;
                }

                long asked;
                var served = long.TryParse(id, out asked) && Provides(key, asked);

                if (Warned.Add("threw|" + key + "|" + id))
                    Plugin.Log.LogError($"RowClone: {key}({id}) THREW "
                        + $"{__exception.GetType().Name} inside the game's own code"
                        + (served
                            ? " even though a clone rule provides that id — the prefix did not "
                              + "serve it, so something asked through a reader we do not hook."
                            : ". Nothing here asked for it and no clone provides it, so a row is "
                              + "pointing at an id this database cannot resolve. THIS IS THE "
                              + "MISSION-HANG: the id above is the one to chase.")
                        + " Reported once per id.");
            }
            catch { }
            return __exception;
        }

        // Does any clone rule answer to this id on this reader?
        private static bool Provides(string key, long id)
        {
            Dictionary<long, CloneSpec> byId;
            CloneSpec s;
            return SingleById.TryGetValue(key, out byId)
                && byId.TryGetValue(id, out s) && !s.Broken;
        }

        private static void MissCheck(string key, List<CloneSpec> specs, object arg, object result)
        {
            try
            {
                long asked;
                try { asked = Convert.ToInt64(arg, CultureInfo.InvariantCulture); }
                catch { return; }
                if (asked <= 0) return;                       // 0 means "no gear", not a miss

                var keyColumn = specs.Count > 0 ? specs[0].KeyColumn : null;
                if (keyColumn == null) return;
                if (KeyOf(result, keyColumn) == asked) return;  // the game has it

                Dictionary<long, CloneSpec> byId;
                CloneSpec ours;
                if (SingleById.TryGetValue(key, out byId) && byId.TryGetValue(asked, out ours)
                    && ours.Materialized && !ours.Broken) return;                 // we serve it

                if (Warned.Add("miss|" + key + "|" + asked))
                    Plugin.Log.LogError($"RowClone: {key}({asked}) found nothing, and no clone "
                        + "rule provides that id. Something points at a row that does not exist. "
                        + "Expect the mission not to load — the game's own exception will not "
                        + "appear in this log. Check which rule sets that id.");
            }
            catch { }
        }

        private static void Complain(MethodBase m, Exception e)
        {
            var key = "err|" + Key(m) + "|" + e.GetType().Name;
            if (Warned.Add(key))
                Plugin.Log.LogWarning($"RowClone[{Key(m)}]: {e.GetType().Name}: {e.Message}  "
                    + "(reported once)");
        }

        // GetMethod by name alone throws on an overload set, and an interop
        // List<T> can carry more than one Add.
        private static string Args(object[] a) =>
            a == null ? "" : string.Join(", ", a.Select(x => x == null ? "null" : x.ToString()));

        // ---- the gate map ----------------------------------------------------
        //
        // Three filtered readers narrow by something a row carries as its own
        // columns, and provenance cannot see any of them. Everything here is
        // the reader's parameter name matched to a column of the same name; no
        // entry is a guess about SQL. A reader not listed falls through to true
        // and provenance decides alone.
        // The clone's own values for the columns a reader is known to gate on,
        // rendered for a log line. Empty when the table has no known gates.
        private static string Gates(CloneSpec s)
        {
            if (s.Template == null) return "";
            var cols = new[] { "MonsterGroupId", "MinPowerLevel", "MaxPowerLevel",
                               "MinSecLevel", "MaxSecLevel", "Faction", "Slot",
                               "MonsterTalentGroup", "PowerGroupId" };
            var parts = new List<string>();
            foreach (var c in cols)
            {
                var p = ModelRules.Prop(s.Template.GetType(), c);
                if (p == null || !p.CanRead) continue;
                try { parts.Add(c + "=" + Convert.ToString(p.GetValue(s.Template),
                                                           CultureInfo.InvariantCulture)); }
                catch { }
            }
            return parts.Count == 0 ? "" : " [" + string.Join(" ", parts) + "]";
        }

        private static bool GatesPass(CloneSpec s, MethodBase m, object[] args)
        {
            if (args == null || args.Length == 0) return true;
            var row = s.Template;
            if (row == null) return true;

            switch (m.Name + "/" + args.Length)
            {
                case "ReadMonsterTypeByPowerGroupId/1":
                    return Eq(row, "PowerGroupId", args[0]);

                case "ReadMonsterGroupMembersByGroup/4":
                    // (monsterGroupId, factionId, powerLevel, secLevel). factionId
                    // is left to provenance: the column is called Faction and
                    // whether 0 means "any" is not established anywhere.
                    return Eq(row, "MonsterGroupId", args[0])
                        && InBand(row, "MinPowerLevel", "MaxPowerLevel", args[2])
                        && InBand(row, "MinSecLevel",   "MaxSecLevel",   args[3]);

                case "ReadMonsterTalents/2":
                    return Eq(row, "MonsterTalentGroup", args[0])
                        && InBand(row, "MinPowerLevel", "MaxPowerLevel", args[1]);

                default:
                    if (Warned.Add("ungated|" + Key(m)))
                        Plugin.Log.LogInfo($"RowClone: {m.Name} filters on arguments this build has "
                            + "no column map for, so only the provenance test applies there. Set "
                            + "\"serveOn\": \"never\" on the clone if that list should not have it.");
                    return true;
            }
        }

        private static bool Eq(object row, string column, object arg)
        {
            var p = ModelRules.Prop(row.GetType(), column);
            if (p == null) return true;             // no such column: not a gate
            var v = p.GetValue(row);
            if (v == null || arg == null) return true;
            try
            {
                return Convert.ToInt64(v, CultureInfo.InvariantCulture)
                    == Convert.ToInt64(arg, CultureInfo.InvariantCulture);
            }
            catch { return true; }
        }

        // A band whose bound is 0 or absent is an open end — that is how the
        // shipped rows express "no floor" and "no cap".
        private static bool InBand(object row, string minColumn, string maxColumn, object arg)
        {
            if (arg == null) return true;
            long v;
            try { v = Convert.ToInt64(arg, CultureInfo.InvariantCulture); }
            catch { return true; }

            long? lo = Num(row, minColumn), hi = Num(row, maxColumn);
            if (lo.HasValue && lo.Value > 0 && v < lo.Value) return false;
            if (hi.HasValue && hi.Value > 0 && v > hi.Value) return false;
            return true;
        }

        private static long? Num(object row, string column)
        {
            var p = ModelRules.Prop(row.GetType(), column);
            if (p == null) return null;
            var v = p.GetValue(row);
            if (v == null) return null;
            try { return Convert.ToInt64(v, CultureInfo.InvariantCulture); }
            catch { return null; }
        }

        // ---- il2cpp method identity ------------------------------------------
        //
        // Two interop proxies that resolve to the same il2cpp method are one
        // method wearing two names, and patching both installs two detours on
        // one address. Il2CppInterop caches each proxy's il2cpp MethodInfo* in
        // a static NativeMethodInfoPtr_<Name>_<signature> field, so that case is
        // visible. The harder case — two genuinely distinct methods folded onto
        // one native body by the linker — is not visible to managed code at all.
        private static readonly Dictionary<IntPtr, string> Claimed =
            new Dictionary<IntPtr, string>();

        private static bool AlreadyClaimed(MethodInfo m, out string owner)
        {
            owner = null;
            var ptr = NativePointer(m);
            if (ptr == IntPtr.Zero) return false;      // unknown: not a claim either way

            string existing;
            if (Claimed.TryGetValue(ptr, out existing) && existing != Key(m))
            { owner = existing; return true; }
            return false;
        }

        // Only after Harmony has actually taken the patch. Claiming at the check
        // would have a refused patch hold the address against its neighbours.
        private static void Claim(MethodInfo m)
        {
            var ptr = NativePointer(m);
            if (ptr != IntPtr.Zero) Claimed[ptr] = Key(m);
        }

        // The field name is NativeMethodInfoPtr_<Name>_<mangled signature>, so a
        // name prefix does not identify one overload. ReadMonsterTalents has two
        // — the zero-arg bulk reader and the (group, powerLevel) filter — and
        // matching on the prefix hands back the same field for both, which would
        // make the two look like one folded method and drop the second. When the
        // prefix is ambiguous, decline to judge rather than judge wrongly.
        private static IntPtr NativePointer(MethodInfo m)
        {
            try
            {
                var fields = m.DeclaringType
                    ?.GetFields(BindingFlags.NonPublic | BindingFlags.Public | BindingFlags.Static)
                    .Where(f => f.FieldType == typeof(IntPtr)
                             && f.Name.StartsWith("NativeMethodInfoPtr_" + m.Name + "_",
                                                  StringComparison.Ordinal))
                    .ToList();
                if (fields == null || fields.Count != 1) return IntPtr.Zero;
                return (IntPtr)fields[0].GetValue(null);
            }
            catch { return IntPtr.Zero; }
        }
    }
}
