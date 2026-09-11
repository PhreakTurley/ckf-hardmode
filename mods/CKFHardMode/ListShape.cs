// ListShape — Count / this[i] / Add on an Il2Cpp list, resolved once.
//
// Serving a clone into a filtered list read means answering "is the row this
// was copied from already in this list?". That was done per clone, and each
// answer walked the whole list through MethodInfo.Invoke — so N clones for a
// table cost N x listLength reflective calls plus a boxed index array each,
// on a reader the game calls while a mission is loading.
//
// Two changes fix it, and this class is the second: the list's own members are
// looked up and compiled once per list type, instead of being re-resolved and
// re-invoked on every call. The first is in RowClone.AfterListRead, which now
// walks the list once to collect the ids it holds and answers every clone from
// that set.

using System;
using System.Collections.Generic;
using System.Linq;
using System.Linq.Expressions;
using System.Reflection;

namespace CKFHardMode
{
    internal sealed class ListShape
    {
        public readonly bool Usable;        // Count and the indexer both resolved
        public readonly bool CanAdd;

        private readonly MethodInfo addM, itemM;
        private readonly PropertyInfo countP;

        private Action<object, object> add;
        private Func<object, int> count;
        private Func<object, int, object> item;

        private static readonly Dictionary<Type, ListShape> Cache =
            new Dictionary<Type, ListShape>();

        public static ListShape For(Type t)
        {
            if (t == null) return null;
            ListShape s;
            if (Cache.TryGetValue(t, out s)) return s;
            Cache[t] = s = new ListShape(t);
            return s;
        }

        private static MethodInfo OneArg(Type t, string name)
        {
            try
            {
                return t.GetMethods(BindingFlags.Public | BindingFlags.Instance)
                        .FirstOrDefault(m => m.Name == name && m.GetParameters().Length == 1);
            }
            catch { return null; }
        }

        private ListShape(Type t)
        {
            addM   = OneArg(t, "Add");
            itemM  = OneArg(t, "get_Item");
            try { countP = t.GetProperty("Count"); } catch { }

            Usable = countP != null && countP.CanRead && itemM != null;
            CanAdd = addM != null;

            if (!Accessor.UseCompiled) return;

            try
            {
                if (countP != null && countP.GetGetMethod(false) != null)
                {
                    var o = Expression.Parameter(typeof(object), "list");
                    count = Expression.Lambda<Func<object, int>>(
                        Expression.Convert(
                            Expression.Property(Expression.Convert(o, t), countP), typeof(int)),
                        o).Compile();
                }
            }
            catch { count = null; }

            try
            {
                if (itemM != null && itemM.IsPublic)
                {
                    var o = Expression.Parameter(typeof(object), "list");
                    var i = Expression.Parameter(typeof(int), "i");
                    var idx = itemM.GetParameters()[0].ParameterType;
                    item = Expression.Lambda<Func<object, int, object>>(
                        Expression.Convert(
                            Expression.Call(Expression.Convert(o, t), itemM,
                                            Expression.Convert(i, idx)), typeof(object)),
                        o, i).Compile();
                }
            }
            catch { item = null; }

            try
            {
                if (addM != null && addM.IsPublic)
                {
                    var o = Expression.Parameter(typeof(object), "list");
                    var v = Expression.Parameter(typeof(object), "row");
                    add = Expression.Lambda<Action<object, object>>(
                        Expression.Call(Expression.Convert(o, t), addM,
                                        Expression.Convert(v, addM.GetParameters()[0].ParameterType)),
                        o, v).Compile();
                }
            }
            catch { add = null; }
        }

        public int Count(object list)
        {
            int n;
            return TryCount(list, out n) ? n : 0;
        }

        // Count that distinguishes "empty" from "could not read". Elapse's
        // board snapshot is replaced only from a read that finished, and a
        // Count that threw must not pass for a finished read of zero rows.
        public bool TryCount(object list, out int n)
        {
            n = 0;
            if (count != null) { try { n = count(list); return true; } catch { return false; } }
            try { n = Convert.ToInt32(countP.GetValue(list)); return true; } catch { return false; }
        }

        public object At(object list, int i)
        {
            if (item != null) { try { return item(list, i); } catch { return null; } }
            try { return itemM.Invoke(list, new object[] { i }); } catch { return null; }
        }

        public bool Add(object list, object row)
        {
            if (add != null) { try { add(list, row); return true; } catch { return false; } }
            try { addM.Invoke(list, new[] { row }); return true; } catch { return false; }
        }

        // Every value of one column across the whole list, in a single pass.
        // This is what replaces a Contains() walk per clone.
        public HashSet<long> ColumnValues(object list, string column)
        {
            var found = new HashSet<long>();
            var n = Count(list);
            Accessor acc = null;

            for (int i = 0; i < n; i++)
            {
                var row = At(list, i);
                if (row == null) continue;
                if (acc == null)
                {
                    acc = Accessors.Get(row.GetType(), column);
                    if (acc == null || !acc.Exists || !acc.Numeric) return found;
                }
                double v;
                if (acc.TryGetNumber(row, out v))
                    found.Add((long)Math.Round(v, MidpointRounding.AwayFromZero));
            }
            return found;
        }
    }
}
