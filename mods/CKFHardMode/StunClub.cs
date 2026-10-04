// A reversible, attack-scoped weapon mechanic. See docs/stunclub.md for the
// metadata declarations and the live checks still needed. No save writes.
using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using HarmonyLib;

namespace CKFHardMode
{
    internal static class StunClub
    {
        internal const long WeaponId = 13000;
        internal const long ExtraPurePercent = 50;
        internal const int TraceLimit = 40;
        private static bool enabled;
        internal static bool Active => enabled;
        private static Type gameWeaponType, weaponType, dualWeaponType;
        private static MethodInfo tryCast;
        private static PropertyInfo pointer, activeWeapon, activeEffect, weaponTypeId,
            weaponId, pureMelee;
        private static PropertyInfo[] damageColumns;
        private static int chanceTraces, hitTraces, rowTraces;
        private static readonly HashSet<string> warnings = new HashSet<string>();

        // Nested calls can use another weapon on the same entity. Remember the
        // contribution already in the aggregate, so a nested club call does
        // not add twice and a nested other-weapon call temporarily removes it.
        [ThreadStatic] private static Dictionary<IntPtr, long> contributions;

        internal sealed class Scope
        {
            internal object Effect;
            internal IntPtr Pointer;
            internal long Before, PreviousBonus, AppliedBonus, UsedWeaponId;
            internal bool HadPrevious, Restored;
            internal string Phase;
        }

        internal static void Init(Harmony harmony)
        {
            if (!Slices.On("StunClub"))
            {
                Plugin.Log.LogInfo(Slices.OffBecause("StunClub",
                    "the club's base damage and attack bonus are not changed."));
                return;
            }
            try
            {
                weaponType = RequireType("RPG.Database.Models.WeaponModel");
                gameWeaponType = RequireType("RPG.Database.Models.GameWeaponModel");
                dualWeaponType = RequireType("RPG.Database.Models.GameWeaponDualModel");
                var provider = RequireType("RPG.Database.Models.IWeaponDataProvider");
                var entity = RequireType("RPG.Core.ICombatEntity");
                var effect = RequireType("RPG.Database.Models.EffectModel");
                var rules = RequireType("RPG.Combat.RulesUtil");
                var db = RequireType("RPG.Database.DataDb");
                var baseObject = RequireType("Il2CppInterop.Runtime.InteropTypes.Il2CppObjectBase");
                pointer = RequireProperty(baseObject, "Pointer", typeof(IntPtr));
                tryCast = baseObject.GetMethods().Single(m => m.Name == "TryCast"
                    && m.IsGenericMethodDefinition && m.GetParameters().Length == 0);
                weaponId = RequireProperty(weaponType, "WeaponId", typeof(long));
                weaponTypeId = RequireProperty(gameWeaponType, "WeaponTypeId", typeof(long));
                activeWeapon = RequireProperty(entity, "ActiveWeapon", provider);
                activeEffect = RequireProperty(entity, "ActiveEffect", effect);
                pureMelee = RequireProperty(effect, "PureDamageMelee", typeof(long), true);
                damageColumns = new[] { "PureDamage1", "PureDamage2",
                    "BallisticDamage1", "BallisticDamage2" }
                    .Select(n => RequireProperty(weaponType, n, typeof(long), true)).ToArray();

                var calculations = CalculationTargets(rules, entity, provider);
                var chance = calculations[0];
                var hit = calculations[1];
                var row = db.GetMethods(BindingFlags.Public | BindingFlags.NonPublic
                    | BindingFlags.Static | BindingFlags.Instance)
                    .Single(m => m.Name == "GetRowWeaponModel" && m.ReturnType == weaponType);
                var seen = new HashSet<IntPtr>();
                foreach (var m in new[] { chance, hit, row })
                {
                    var native = NativePointer(m);
                    if (native != IntPtr.Zero && !seen.Add(native))
                        throw new InvalidOperationException("duplicate native proxy target: " + m.Name);
                }

                var finish = new HarmonyMethod(typeof(StunClub), nameof(AfterCalculation));
                var unwind = new HarmonyMethod(typeof(StunClub), nameof(CalculationThrew));
                // Everything stays inert until ALL required hooks are installed.
                harmony.Patch(chance,
                    prefix: new HarmonyMethod(typeof(StunClub), nameof(BeforeChance)),
                    postfix: finish, finalizer: unwind);
                harmony.Patch(hit,
                    prefix: new HarmonyMethod(typeof(StunClub), nameof(BeforeHit)),
                    postfix: finish, finalizer: unwind);
                harmony.Patch(row, postfix: new HarmonyMethod(typeof(StunClub), nameof(AfterWeaponRow))
                {
                    priority = Priority.Last,
                    after = new[] { Plugin.PluginGuid + ".models" }
                });
                StunClubPresentation.Init(harmony);
                enabled = true;
                Plugin.Log.LogInfo("StunClub: enabled for WeaponModel[13000]. Base pure/ballistic "
                    + "damage is cleared; calculation scopes add 50 to ActiveEffect.PureDamageMelee "
                    + "and restore it afterwards. Hooks: CalculateAttackChance, ResolveDamageOnHit, "
                    + "DataDb.GetRowWeaponModel. First " + TraceLimit + " chance calculations and first "
                    + TraceLimit + " hits log weapon identity, the temporary stat and restoration; "
                    + "each phase reports when its separate trace limit is reached. "
                    + "Talent coverage and stacking need a live check.");
            }
            catch (Exception e)
            {
                enabled = false;
                Plugin.Log.LogError("StunClub: initialisation refused; ALL its hooks are inert. " + e);
            }
        }

        public static void AfterWeaponRow(object __result)
        {
            if (!enabled || __result == null) return;
            try
            {
                if ((long)weaponId.GetValue(__result) != WeaponId) return;
                var before = damageColumns.Select(p => (long)p.GetValue(__result)).ToArray();
                try
                {
                    foreach (var p in damageColumns) p.SetValue(__result, 0L);
                    if (damageColumns.Any(p => (long)p.GetValue(__result) != 0))
                        throw new InvalidOperationException("a base-damage setter discarded the write");
                }
                catch
                {
                    for (int i = 0; i < damageColumns.Length; i++)
                        damageColumns[i].SetValue(__result, before[i]);
                    throw;
                }
                if (rowTraces++ < 3)
                    Plugin.Log.LogInfo("StunClub: WeaponModel[13000] "
                        + string.Join(", ", damageColumns.Select((p, i) => p.Name + " " + before[i] + " -> 0"))
                        + "; kinetic columns and WeaponEffect untouched.");
            }
            catch (Exception e) { Refuse("base damage", e); }
        }

        public static void BeforeChance(object[] __args, out Scope __state)
        {
            __state = null;
            if (!enabled) return;
            try
            {
                if (__args == null || __args.Length != 6)
                    throw new InvalidOperationException("could not read attack-chance arguments");
                __state = Enter(__args[0], __args[1], "chance");
            }
            catch (Exception e) { Refuse("chance scope", e); }
        }

        public static void BeforeHit(object[] __args, out Scope __state)
        {
            __state = null;
            if (!enabled) return;
            try
            {
                if (__args == null || __args.Length != 4 || __args[0] == null)
                    throw new InvalidOperationException("could not read hit-resolution arguments");
                // This method has no weapon parameter. Read the entity's current
                // ActiveWeapon at the calculation, never its equipped loadout.
                __state = Enter(__args[0], activeWeapon.GetValue(__args[0]), "hit");
            }
            catch (Exception e) { Refuse("hit scope", e); }
        }

        internal static Scope Enter(object attacker, object weapon, string phase)
        {
            if (attacker == null || weapon == null)
                throw new InvalidOperationException("attacker or calculation weapon is null");
            long id = ContentWeaponId(weapon);
            var effect = activeEffect.GetValue(attacker);
            if (effect == null)
                throw new InvalidOperationException("ActiveEffect is null; could not read the aggregate");
            var key = (IntPtr)pointer.GetValue(effect);
            if (key == IntPtr.Zero) throw new InvalidOperationException("ActiveEffect has no native pointer");
            if (contributions == null) contributions = new Dictionary<IntPtr, long>();
            var state = new Scope { Effect = effect, Pointer = key,
                Before = (long)pureMelee.GetValue(effect), UsedWeaponId = id, Phase = phase,
                AppliedBonus = id == WeaponId ? ExtraPurePercent : 0 };
            state.HadPrevious = contributions.TryGetValue(key, out state.PreviousBonus);
            long desired = checked(state.Before - state.PreviousBonus + state.AppliedBonus);
            try
            {
                pureMelee.SetValue(effect, desired);
                if ((long)pureMelee.GetValue(effect) != desired)
                    throw new InvalidOperationException("PureDamageMelee setter discarded the write");
                contributions[key] = state.AppliedBonus;
                return state;
            }
            catch
            {
                Restore(state);
                throw;
            }
        }

        internal static long ContentWeaponId(object weapon)
        {
            // IWeaponDataProvider.Id is NOT assumed to be a content id.
            // GameWeaponModel identifies it with WeaponTypeId; a direct
            // WeaponModel identifies it with WeaponId. Dual providers are
            // excluded rather than granting a bonus to their other weapon.
            var game = As(weapon, gameWeaponType);
            if (game != null) return (long)weaponTypeId.GetValue(game);
            var data = As(weapon, weaponType);
            if (data != null) return (long)weaponId.GetValue(data);
            if (As(weapon, dualWeaponType) != null) return -1; // never boost a combined attack
            throw new InvalidOperationException("unsupported weapon provider " + weapon.GetType().FullName
                + "; could not establish a single WeaponModel id");
        }

        private static object As(object obj, Type target)
        {
            if (target.IsInstanceOfType(obj)) return obj;
            return tryCast.MakeGenericMethod(target).Invoke(obj, null);
        }

        public static void AfterCalculation(Scope __state)
        {
            if (__state == null) return;
            try
            {
                long during = (long)pureMelee.GetValue(__state.Effect);
                Restore(__state);
                // Preview traffic must never consume the hit sample budget.
                bool isHit = __state.Phase == "hit";
                int count = isHit ? hitTraces : chanceTraces;
                if (count < TraceLimit)
                {
                    if (isHit) hitTraces++;
                    else chanceTraces++;
                    Plugin.Log.LogInfo("StunClub: " + __state.Phase + " "
                        + (__state.UsedWeaponId == -1 ? "combined dual provider"
                            : "WeaponModel[" + __state.UsedWeaponId + "]")
                        + " PureDamageMelee " + __state.Before
                        + " -> " + during + " -> " + pureMelee.GetValue(__state.Effect)
                        + "; club contribution " + __state.AppliedBonus + "; complete=true.");
                    if (count + 1 == TraceLimit)
                        Plugin.Log.LogInfo("StunClub: " + __state.Phase + " trace limit reached ("
                            + TraceLimit + "); subsequent " + __state.Phase + " calculations are not logged. "
                            + "Stat edits and restoration remain active; the other phase has a separate limit.");
                }
            }
            catch (Exception e) { Refuse("restoration", e); }
        }

        public static Exception CalculationThrew(Exception __exception, Scope __state)
        {
            // A postfix alone cannot restore after an exception. Do not swallow
            // the game's exception, and do not depend on enabled when unwinding.
            try { Restore(__state); }
            catch (Exception e) { Refuse("exception restoration", e); }
            return __exception;
        }

        internal static void Restore(Scope state)
        {
            if (state == null || state.Restored) return;
            pureMelee.SetValue(state.Effect, state.Before);
            if ((long)pureMelee.GetValue(state.Effect) != state.Before)
                throw new InvalidOperationException("PureDamageMelee was not restored");
            if (state.HadPrevious) contributions[state.Pointer] = state.PreviousBonus;
            else contributions.Remove(state.Pointer);
            state.Restored = true;
        }

        private static void Refuse(string phase, Exception error)
        {
            enabled = false;
            if (warnings.Add(phase))
                Plugin.Log.LogError("StunClub: " + phase + " complete=false; " + error
                    + ". Further club edits are disabled this launch; reload with StunClub=false "
                    + "to discard any already materialized base-damage edits.");
        }

        internal static Type RequireType(string name) => AccessTools.TypeByName(name)
            ?? throw new MissingMemberException(name);

        internal static PropertyInfo RequireProperty(Type type, string name, Type valueType, bool writable = false)
        {
            var p = type.GetProperty(name);
            if (p == null || p.PropertyType != valueType || !p.CanRead || (writable && !p.CanWrite))
                throw new MissingMemberException(type.FullName, name);
            return p;
        }

        // Reflection includes the declaring type in a nested type's FullName.
        // These targets are also checked against the installed interop metadata
        // by the offline harness, without executing a native method.
        private static MethodInfo[] CalculationTargets(Type rules, Type entity, Type provider)
        {
            return new[]
            {
                RequireMethod(rules, "CalculateAttackChance", "RPG.Combat.AttackChance",
                    entity.FullName, provider.FullName, entity.FullName, "RPG.Combat.AttackVector",
                    "Il2CppSystem.Collections.Generic.Dictionary`2", "RPG.Core.Constants+CombatRuleHints"),
                RequireMethod(rules, "ResolveDamageOnHit", "RPG.Combat.DamageResult",
                    entity.FullName, entity.FullName, "RPG.Combat.AttackVector", "RPG.Combat.AttackResult")
            };
        }

        private static string ParameterTypeName(Type type) => type.IsGenericType
            ? type.GetGenericTypeDefinition().FullName : type.FullName;

        private static MethodInfo RequireMethod(Type type, string name, string result, params string[] args)
        {
            var candidates = type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static)
                .Where(m => m.Name == name).ToArray();
            var matches = candidates.Where(m => m.ReturnType.FullName == result
                && m.GetParameters().Select(p => ParameterTypeName(p.ParameterType)).SequenceEqual(args)).ToArray();
            if (matches.Length != 1)
                throw new MissingMethodException("Expected exactly one " + type.FullName + "." + name
                    + "(" + string.Join(", ", args) + ") -> " + result + "; found " + matches.Length
                    + ". Available: " + string.Join("; ", candidates.Select(m => m.Name + "("
                        + string.Join(", ", m.GetParameters().Select(p => ParameterTypeName(p.ParameterType)))
                        + ") -> " + m.ReturnType.FullName)));
            return matches[0];
        }

        private static IntPtr NativePointer(MethodInfo method)
        {
            var f = method.DeclaringType.GetFields(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static)
                .SingleOrDefault(p => p.FieldType == typeof(IntPtr)
                    && p.Name.StartsWith("NativeMethodInfoPtr_" + method.Name + "_", StringComparison.Ordinal));
            return f == null ? IntPtr.Zero : (IntPtr)f.GetValue(null);
        }
    }
}
