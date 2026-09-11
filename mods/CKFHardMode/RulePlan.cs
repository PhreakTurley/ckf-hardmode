// RulePlan — what the per-row postfix actually walks.
//
// The postfix used to test EVERY rule for a table against EVERY row. At 433
// rules a full ReadArmors() is ~127k Matches() calls, and the cost grows with
// the file: the whole point of the CSV overlays is that the file gets much
// bigger.
//
// It does not need to. Of the 325 non-clone rules in the live file, 283 are a
// single exact match on a domain id — where: { "EffectId": 1234 }. All 133
// EffectModel rules are that shape, and so are all 72 JobNodeModel rules. A
// row carrying EffectId 1234 can only ever match the handful of rules that
// named 1234, and testing it against the other 132 is pure waste.
//
// So each model gets a plan: one column chosen as the index, a bucket per
// value of it, and a list of everything that could not be indexed (range
// selectors, string selectors, whole-table rules). Per row that is one number
// read and one dictionary lookup, and then only the rules that could possibly
// match get tested.
//
// ORDER IS PRESERVED. Rules apply in file order and some files depend on it —
// a broad multiply followed by a narrow clampMax is not the same as the
// reverse. Both the bucket and the unindexed list are in file order, so Run
// merge-walks them on Rule.Index rather than concatenating.
//
// The index is chosen, never configured. If a model's rules do not share a
// dominant exact-match column the plan holds no index and behaves exactly as
// before, which is why a whole-table sweep rule still works.

using System;
using System.Collections.Generic;
using System.Reflection;
using System.Text.Json;

namespace CKFHardMode
{
    internal sealed class ModelPlan
    {
        public readonly string ModelName;
        public readonly List<Rule> Rules;

        // The column the buckets are keyed on. Null means no index — every
        // rule is tested against every row, as it was before.
        public string IndexColumn { get; private set; }

        private Dictionary<long, List<Rule>> buckets;
        private List<Rule> unindexed;

        // Resolved on the first row, because the row's concrete type is not
        // known until then. A model always materializes as one type; if that
        // ever stops being true the plan rebuilds rather than misreading.
        private Type builtFor;
        private Accessor keyAcc;
        private bool indexUsable;

        public ModelPlan(string modelName, List<Rule> rules, bool noIndex = false)
        {
            ModelName = modelName;
            Rules = rules ?? new List<Rule>();
            if (!noIndex) Choose();
        }

        // ---- choosing the index column --------------------------------------

        // An exact selector on an integer-valued number is indexable. A range
        // selector is not (it spans buckets), and neither is a string or a
        // fractional number.
        private static bool Indexable(JsonElement v, out long key)
        {
            key = 0;
            if (v.ValueKind != JsonValueKind.Number) return false;
            double d;
            if (!v.TryGetDouble(out d)) return false;
            if (Math.Abs(d - Math.Round(d)) > 1e-9) return false;
            if (d < long.MinValue || d > long.MaxValue) return false;
            key = (long)Math.Round(d);
            return true;
        }

        // Worth indexing only when it removes real work: enough rules for the
        // scan to cost something, and enough of them sharing one column that
        // the extra number read per row pays for itself.
        private const int MinRules = 8;

        private void Choose()
        {
            if (Rules.Count < MinRules) return;

            var counts = new Dictionary<string, int>(StringComparer.Ordinal);
            foreach (var r in Rules)
            {
                // An overlay line is already exactly one id against one column,
                // which is what the index wants; it needs no JSON inspection.
                if (r.OverlayKeyColumn != null)
                {
                    int m;
                    counts.TryGetValue(r.OverlayKeyColumn, out m);
                    counts[r.OverlayKeyColumn] = m + 1;
                    continue;
                }

                if (r.Where == null) continue;
                foreach (var kv in r.Where)
                {
                    long ignored;
                    if (!Indexable(kv.Value, out ignored)) continue;
                    int n;
                    counts.TryGetValue(kv.Key, out n);
                    counts[kv.Key] = n + 1;
                }
            }

            string best = null;
            int bestCount = 0;
            foreach (var kv in counts)
                if (kv.Value > bestCount || (kv.Value == bestCount &&
                        string.CompareOrdinal(kv.Key, best) < 0))
                { best = kv.Key; bestCount = kv.Value; }

            if (best == null || bestCount * 2 < Rules.Count) return;

            IndexColumn = best;
            buckets = new Dictionary<long, List<Rule>>();
            unindexed = new List<Rule>();

            foreach (var r in Rules)
            {
                JsonElement v;
                long key = 0;
                bool indexed = r.OverlayKeyColumn == best;
                if (indexed) key = r.OverlayKeyValue;
                else if (r.OverlayKeyColumn == null && r.Where != null
                         && r.Where.TryGetValue(best, out v))
                    indexed = Indexable(v, out key);

                if (indexed)
                {
                    List<Rule> bucket;
                    if (!buckets.TryGetValue(key, out bucket))
                        buckets[key] = bucket = new List<Rule>();
                    bucket.Add(r);
                }
                else unindexed.Add(r);
            }
        }

        // A one-line summary for the load log, so a file that indexes badly is
        // visible rather than merely slow.
        public string Describe()
        {
            if (IndexColumn == null)
                return $"{ModelName}: {Rules.Count} rule(s), no index (every row tests all of them)";

            long worst = 0;
            foreach (var b in buckets.Values) if (b.Count > worst) worst = b.Count;
            return $"{ModelName}: {Rules.Count} rule(s) indexed on {IndexColumn} — "
                 + $"{buckets.Count} value(s), worst bucket {worst}, "
                 + $"{unindexed.Count} unindexed";
        }

        // ---- the hot path ----------------------------------------------------

        private void Bind(Type rowType)
        {
            builtFor = rowType;
            indexUsable = false;
            if (IndexColumn == null) return;

            keyAcc = Accessors.Get(rowType, IndexColumn);
            indexUsable = keyAcc != null && keyAcc.Exists && keyAcc.Numeric;

            if (!indexUsable)
                Plugin.Log.LogWarning($"ModelRules: {ModelName} has no readable numeric "
                    + $"'{IndexColumn}', so its rules are matched one by one. This is correct, "
                    + "just slower — check the column name against the dump CSV.");
        }

        public void Run(object row)
        {
            if (Rules.Count == 0) return;

            var t = row.GetType();
            if (!ReferenceEquals(builtFor, t)) Bind(t);

            if (!indexUsable) { foreach (var r in Rules) Fire(row, r); return; }

            double d;
            List<Rule> bucket = null;
            if (keyAcc.TryGetNumber(row, out d))
            {
                var key = (long)Math.Round(d, MidpointRounding.AwayFromZero);
                buckets.TryGetValue(key, out bucket);
            }

            // Merge-walk, so a bucketed rule and an unindexed one still fire in
            // the order the file lists them.
            int i = 0, j = 0;
            int ni = bucket == null ? 0 : bucket.Count, nj = unindexed.Count;
            while (i < ni || j < nj)
            {
                if (j >= nj || (i < ni && bucket[i].Index <= unindexed[j].Index))
                    Fire(row, bucket[i++]);
                else
                    Fire(row, unindexed[j++]);
            }
        }

        private void Fire(object row, Rule rule)
        {
            try
            {
                if (!ModelRules.Matches(row, rule)) return;
                ModelRules.Apply(row, rule);
            }
            catch (Exception e)
            {
                ModelRules.ReportRuleError(ModelName, rule, e);
            }
        }
    }
}
