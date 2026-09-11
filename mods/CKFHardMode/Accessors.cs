// Accessors — compiled property access for the rule hot path.
//
// Rules are matched and applied per ROW, and every column touch used to go
// through PropertyInfo.GetValue / SetValue plus a string-concatenated cache
// key. On a full ReadArmors() at 433 rules that is ~127k reflective calls and
// ~127k throwaway strings.
//
// An Accessor resolves one (row type, column) pair ONCE and holds delegates
// for it. The delegates are built with expression trees, which BepInEx 6 runs
// on CoreCLR, so they compile to real IL and cost about what a direct property
// call costs. Il2CppInterop model classes are ordinary managed proxy types, so
// there is nothing exotic to compile against.
//
// THE ONE THING THAT MUST NOT DRIFT is the numeric conversion. The old path
// wrote values back with Convert.ChangeType(double, columnType), which rounds
// to nearest and sends halves to even — 25 x 1.5 stores 38, not 37. A plain
// (long) cast in IL truncates instead, which would quietly shave a point off
// every rounded stat in the file. SetNumber therefore rounds with
// MidpointRounding.ToEven before converting, and AccessorTests checks that
// against Convert.ChangeType across the awkward values.
//
// A WRITE THAT CANNOT LAND NOW SAYS WHY. SetNumber and SetRaw return a
// WriteResult rather than a bool, so a caller can tell an overflow apart from a
// value of the wrong shape and from a column with no setter, and report it.
// They still never throw into the game's call path.
//
// Everything degrades to reflection rather than failing:
//   - a column that does not exist            -> Exists is false
//   - a non-public or unusual property        -> reflection delegates
//   - Expression.Compile() throwing at all    -> reflection delegates
//   - [ModelRules] CompiledAccessors = false  -> reflection everywhere (a key that
//     was removed in 2.12.0, before the section moved into ckf.hardmode.json)
//
// so a build where codegen is unavailable behaves exactly as 2.5.2 did, only
// slower.

using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq.Expressions;
using System.Reflection;

namespace CKFHardMode
{
    // What happened to one attempted write.
    //
    // SetNumber and SetRaw used to return a bare bool, and every caller
    // discarded it — so an overflow on an int column, a string value that is
    // not a number, and a column with no setter at all were three different
    // faults that all looked like "the rule matched and changed nothing". The
    // reason travels back with the answer now, and ModelRules reports it once
    // per (type, column, reason).
    internal enum WriteResult
    {
        Ok,
        NotWritable,    // no property, or no setter
        NullValue,      // SetRaw was handed null; there is nothing to store
        Overflow,       // the value does not fit the column's type
        Conversion,     // the value is not of a shape the column can hold
        Failed,         // the setter itself threw something else
    }

    internal sealed class Accessor
    {
        public readonly Type Owner;
        public readonly string Name;
        public readonly PropertyInfo Prop;

        // The column's type with Nullable<> peeled off, as the old
        // ModelRules.Underlying returned.
        public readonly Type Underlying;

        public bool Exists => Prop != null;
        public bool CanWrite => Prop != null && Prop.CanWrite;

        // True when the column holds something a curve or a clamp can work on.
        // Strings and bools are readable and writable but not arithmetic.
        public readonly bool Numeric;

        // Compiled when possible, null when we fell back to reflection.
        private Func<object, double> getNum;
        private Action<object, double> setNum;
        private Func<object, object> getObj;
        private Action<object, object> setObj;

        internal static bool UseCompiled = true;

        internal Accessor(Type owner, string name, PropertyInfo prop)
        {
            Owner = owner;
            Name = name;
            Prop = prop;
            if (prop == null) return;

            Underlying = Nullable.GetUnderlyingType(prop.PropertyType) ?? prop.PropertyType;
            Numeric = IsNumeric(Underlying);

            if (UseCompiled) Build();
        }

        private static bool IsNumeric(Type t)
        {
            if (t == null) return false;
            if (t.IsEnum) return true;
            switch (Type.GetTypeCode(t))
            {
                case TypeCode.Byte:  case TypeCode.SByte:
                case TypeCode.Int16: case TypeCode.UInt16:
                case TypeCode.Int32: case TypeCode.UInt32:
                case TypeCode.Int64: case TypeCode.UInt64:
                case TypeCode.Single: case TypeCode.Double:
                case TypeCode.Decimal:
                    return true;
                default:
                    return false;
            }
        }

        // Only compile against a property we are certain a DynamicMethod may
        // touch. A non-public accessor, a Nullable<> column or an indexer all
        // go the reflection route rather than risk a MethodAccessException on
        // the game's hot path.
        private bool Compilable(MethodInfo m) =>
            m != null && m.IsPublic && !m.IsStatic
            && (Prop.DeclaringType == null || !Prop.DeclaringType.IsGenericTypeDefinition)
            && Prop.GetIndexParameters().Length == 0
            && Nullable.GetUnderlyingType(Prop.PropertyType) == null;

        private void Build()
        {
            var declaring = Prop.DeclaringType ?? Owner;
            var getter = Prop.GetGetMethod(false);
            var setter = Prop.GetSetMethod(false);

            try
            {
                if (Compilable(getter))
                {
                    var p = Expression.Parameter(typeof(object), "row");
                    Expression access = Expression.Property(
                        Expression.Convert(p, declaring), Prop);

                    getObj = Expression.Lambda<Func<object, object>>(
                        Expression.Convert(access, typeof(object)), p).Compile();

                    if (Numeric)
                    {
                        // enum -> its underlying integer -> double, so a column
                        // typed as an enum still reads as a number the way
                        // Convert.ToDouble made it.
                        var num = Underlying.IsEnum
                            ? Expression.Convert(access, Enum.GetUnderlyingType(Underlying))
                            : (Expression)access;
                        getNum = Expression.Lambda<Func<object, double>>(
                            Expression.Convert(num, typeof(double)), p).Compile();
                    }
                }
            }
            catch { getNum = null; getObj = null; }

            try
            {
                if (Compilable(setter))
                {
                    var p = Expression.Parameter(typeof(object), "row");
                    var target = Expression.Convert(p, declaring);

                    var v = Expression.Parameter(typeof(object), "value");
                    setObj = Expression.Lambda<Action<object, object>>(
                        Expression.Assign(Expression.Property(target, Prop),
                                          Expression.Convert(v, Prop.PropertyType)),
                        p, v).Compile();

                    if (Numeric)
                    {
                        var d = Expression.Parameter(typeof(double), "value");
                        Expression store = Rounded(d, Underlying);
                        if (Underlying.IsEnum)
                            store = Expression.Convert(
                                Rounded(d, Enum.GetUnderlyingType(Underlying)), Underlying);

                        setNum = Expression.Lambda<Action<object, double>>(
                            Expression.Assign(Expression.Property(target, Prop), store),
                            p, d).Compile();
                    }
                }
            }
            catch { setNum = null; setObj = null; }
        }

        // double -> the column's type, matching Convert.ChangeType exactly:
        // nearest, halves to even, and an overflow throws rather than wrapping.
        private static readonly MethodInfo RoundToEven = typeof(Math).GetMethod(
            "Round", new[] { typeof(double), typeof(MidpointRounding) });

        private static Expression Rounded(Expression d, Type target)
        {
            var code = Type.GetTypeCode(target);
            bool integral = code != TypeCode.Single && code != TypeCode.Double
                                                    && code != TypeCode.Decimal;
            if (!integral) return Expression.Convert(d, target);

            return Expression.ConvertChecked(
                Expression.Call(RoundToEven, d,
                                Expression.Constant(MidpointRounding.ToEven)),
                target);
        }

        // ---- reading -------------------------------------------------------

        // False means "no usable number here" — the column is missing, holds
        // null, or is not arithmetic. Callers skip the row, which is what the
        // reflection path did when GetValue returned null.
        public bool TryGetNumber(object row, out double value)
        {
            value = 0.0;
            if (Prop == null) return false;

            if (getNum != null)
            {
                try { value = getNum(row); return true; }
                catch { return false; }
            }

            try
            {
                var v = Prop.GetValue(row);
                if (v == null) return false;
                value = Convert.ToDouble(v, CultureInfo.InvariantCulture);
                return true;
            }
            catch { return false; }
        }

        public object GetRaw(object row)
        {
            if (Prop == null) return null;
            if (getObj != null) { try { return getObj(row); } catch { return null; } }
            try { return Prop.GetValue(row); } catch { return null; }
        }

        // ---- writing -------------------------------------------------------

        // Why a write failed, off the exception it failed with. Reflection
        // wraps a setter's own exception in a TargetInvocationException, so the
        // inner one is what carries the reason; Rounded's ConvertChecked and
        // Convert.ChangeType both throw OverflowException directly.
        private static WriteResult Classify(Exception e)
        {
            var inner = e is TargetInvocationException && e.InnerException != null
                      ? e.InnerException : e;
            if (inner is OverflowException) return WriteResult.Overflow;
            if (inner is InvalidCastException || inner is FormatException
                || inner is ArgumentException) return WriteResult.Conversion;
            return WriteResult.Failed;
        }

        // Nothing here throws into the game's call path: every failure comes
        // back as a WriteResult for the caller to report.
        public WriteResult SetNumber(object row, double value)
        {
            if (Prop == null || !Prop.CanWrite) return WriteResult.NotWritable;

            if (setNum != null)
            {
                try { setNum(row, value); return WriteResult.Ok; }
                catch (Exception e) { return Classify(e); }
            }

            try
            {
                Prop.SetValue(row, Convert.ChangeType(value, Underlying,
                                                     CultureInfo.InvariantCulture));
                return WriteResult.Ok;
            }
            catch (Exception e) { return Classify(e); }
        }

        public WriteResult SetRaw(object row, object value)
        {
            if (Prop == null || !Prop.CanWrite) return WriteResult.NotWritable;
            if (value == null) return WriteResult.NullValue;

            if (setObj != null)
            {
                try { setObj(row, value); return WriteResult.Ok; }
                catch { /* fall through to reflection, which may still take it */ }
            }

            try { Prop.SetValue(row, value); return WriteResult.Ok; }
            catch (Exception e) { return Classify(e); }
        }
    }

    internal static class Accessors
    {
        // (row type, column) -> Accessor, misses cached as an Accessor with a
        // null Prop so a mistyped column costs one dictionary hit, not a
        // reflection walk per row.
        private static readonly Dictionary<Type, Dictionary<string, Accessor>> Cache =
            new Dictionary<Type, Dictionary<string, Accessor>>();

        public static Accessor Get(Type t, string column)
        {
            if (t == null || string.IsNullOrEmpty(column)) return null;

            Dictionary<string, Accessor> byName;
            if (!Cache.TryGetValue(t, out byName))
                Cache[t] = byName = new Dictionary<string, Accessor>(StringComparer.Ordinal);

            Accessor a;
            if (byName.TryGetValue(column, out a)) return a;

            // ModelRules.Prop already walks the inheritance chain — a model's
            // columns live on its *Base type, not the leaf — and caches the
            // answer, including the misses.
            a = new Accessor(t, column, ModelRules.Prop(t, column));
            byName[column] = a;
            return a;
        }

        // The reason half of a write-failure message, in the terms the rules
        // file is written in rather than in exception names.
        public static string Why(WriteResult r, Accessor a)
        {
            var type = a?.Underlying?.Name ?? "that column's type";
            switch (r)
            {
                case WriteResult.NotWritable: return "the column has no setter";
                case WriteResult.NullValue:   return "the value is null, so there is nothing to store";
                case WriteResult.Overflow:    return "the result does not fit " + type;
                case WriteResult.Conversion:  return "the value is not a " + type;
                default:                      return "the setter threw";
            }
        }

        // Called from Init so the toggle is settled before anything is built.
        public static void Configure(bool compiled)
        {
            Accessor.UseCompiled = compiled;
            Cache.Clear();
        }
    }
}
