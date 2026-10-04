using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Resources;
using System.Text.Json;
using HarmonyLib;

namespace CKFHardMode
{
    internal static class StunClubPresentation
    {
        internal const string TitleKey = "CKFHardMode.Weapon.KineticAsExtraPure.Title";
        internal const string DescriptionKey = "CKFHardMode.Weapon.KineticAsExtraPure.Description";
        private static ConstructorInfo listConstructor, ruleConstructor, textConstructor;
        private static PropertyInfo count, item, title, description, translationData,
            asObject, dictionary, localeItem, localeValue;
        private static MethodInfo add, containsKey;
        private static Dictionary<string, string> english;
        private static int traces;
        private static readonly HashSet<string> warnings = new HashSet<string>();

        internal static void Init(Harmony harmony)
        {
            var target = Prepare(StunClub.RequireType("RPG.Database.Models.GameWeaponModel"),
                StunClub.RequireType("CommerceItemSpecialRule"), StunClub.RequireType("RPG.Core.I18n"),
                StunClub.RequireType("Lib.SimpleJSON.JSONNode"),
                StunClub.RequireType("Lib.SimpleJSON.JSONClass"),
                StunClub.RequireType("Lib.SimpleJSON.JSONData"));
            harmony.Patch(target, postfix: new HarmonyMethod(typeof(StunClubPresentation), nameof(AfterRules)));
            Plugin.Log.LogInfo("StunClub UI: installed GameWeaponModel.CommerceItemSpecialRules hook. "
                + "Locale keys: " + TitleKey + ", " + DescriptionKey + ". First 8 appended entries log readback.");
        }

        // Resolve metadata without executing native constructors or reading locale state.
        private static MethodInfo Prepare(Type weapon, Type rule, Type i18n, Type node, Type jsonClass, Type text)
        {
            var rules = weapon.GetProperty("CommerceItemSpecialRules")
                ?? throw new MissingMemberException(weapon.FullName, "CommerceItemSpecialRules");
            var list = rules.PropertyType;
            if (!list.IsGenericType || list.GetGenericTypeDefinition().FullName != "Il2CppSystem.Collections.Generic.List`1"
                || !list.GetGenericArguments().SequenceEqual(new[] { rule }))
                throw new InvalidOperationException("Unexpected CommerceItemSpecialRules list declaration: " + list.FullName);
            listConstructor = Constructor(list);
            ruleConstructor = Constructor(rule);
            count = StunClub.RequireProperty(list, "Count", typeof(int));
            item = list.GetProperty("Item", new[] { typeof(int) });
            if (item == null || item.PropertyType != rule || !item.CanRead)
                throw new MissingMemberException(list.FullName, "Item[int]");
            add = list.GetMethod("Add", new[] { rule }) ?? throw new MissingMethodException(list.FullName, "Add");
            title = StunClub.RequireProperty(rule, "RuleTitle", typeof(string), true);
            description = StunClub.RequireProperty(rule, "RuleDescription", typeof(string), true);
            translationData = StunClub.RequireProperty(i18n, "translationData", node);
            asObject = StunClub.RequireProperty(node, "AsObject", jsonClass);
            dictionary = jsonClass.GetProperty("m_Dict")
                ?? throw new MissingMemberException(jsonClass.FullName, "m_Dict");
            containsKey = dictionary.PropertyType.GetMethod("ContainsKey", new[] { typeof(string) })
                ?? throw new MissingMethodException(dictionary.PropertyType.FullName, "ContainsKey");
            localeItem = node.GetProperty("Item", new[] { typeof(string) });
            if (localeItem == null || localeItem.PropertyType != node || !localeItem.CanRead || !localeItem.CanWrite)
                throw new MissingMemberException(node.FullName, "Item[string]");
            localeValue = StunClub.RequireProperty(node, "Value", typeof(string));
            textConstructor = Constructor(text, typeof(string));
            using (var stream = typeof(StunClubPresentation).Assembly.GetManifestResourceStream("CKFHardMode.WeaponLocale.en-US.json")
                ?? throw new MissingManifestResourceException("CKFHardMode.WeaponLocale.en-US.json"))
            using (var reader = new StreamReader(stream))
                english = JsonSerializer.Deserialize<Dictionary<string, string>>(reader.ReadToEnd());
            if (english == null || english.Count != 2 || !english.ContainsKey(TitleKey) || !english.ContainsKey(DescriptionKey))
                throw new InvalidOperationException("Weapon locale resource must declare exactly the title and description keys");
            return rules.GetGetMethod() ?? throw new MissingMethodException(weapon.FullName, "get_CommerceItemSpecialRules");
        }

        private static ConstructorInfo Constructor(Type type, params Type[] args) => type.GetConstructor(args)
            ?? throw new MissingMethodException(type.FullName, ".ctor(" + string.Join(",", args.Select(t => t.FullName)) + ")");

        public static void AfterRules(object __instance, ref object __result)
        {
            if (!StunClub.Active || __instance == null) return;
            try
            {
                if (StunClub.ContentWeaponId(__instance) != StunClub.WeaponId) return;
                // Read the CURRENT language dictionary each time. Never cache a
                // native locale object, or replace an existing translation.
                var root = translationData.GetValue(null)
                    ?? throw new InvalidOperationException("active locale dictionary is unavailable");
                string caption = LocalizedText(root, TitleKey);
                string detail = LocalizedText(root, DescriptionKey);
                var copy = listConstructor.Invoke(Array.Empty<object>());
                bool present = false;
                int originalCount = __result == null ? 0 : (int)count.GetValue(__result);
                for (int i = 0; i < originalCount; i++)
                {
                    var existing = item.GetValue(__result, new object[] { i });
                    if (existing != null && (string)title.GetValue(existing) == caption
                        && (string)description.GetValue(existing) == detail) present = true;
                    add.Invoke(copy, new[] { existing });
                }
                if (!present)
                {
                    var entry = ruleConstructor.Invoke(Array.Empty<object>());
                    title.SetValue(entry, caption);
                    description.SetValue(entry, detail);
                    if ((string)title.GetValue(entry) != caption || (string)description.GetValue(entry) != detail)
                        throw new InvalidOperationException("special-rule text setter discarded a write");
                    add.Invoke(copy, new[] { entry });
                }
                int resultCount = (int)count.GetValue(copy);
                if (resultCount != originalCount + (present ? 0 : 1))
                    throw new InvalidOperationException("special-rule list did not retain its entries");
                // Publish only the completed copy. Preserve any cached/shared
                // source list and all its existing crit/stun/special-rule rows.
                if (traces++ < 8)
                    Plugin.Log.LogInfo("StunClub UI: WeaponModel[13000] rules " + originalCount + " -> "
                        + resultCount + "; title=" + caption + "; description=" + detail + "; complete=true.");
                __result = copy;
            }
            catch (Exception e)
            {
                if (warnings.Add(e.Message))
                    Plugin.Log.LogError("StunClub UI: complete=false; existing rules preserved. " + e);
            }
        }

        private static string LocalizedText(object root, string key)
        {
            var obj = asObject.GetValue(root)
                ?? throw new InvalidOperationException("active locale root is not an object");
            var map = dictionary.GetValue(obj)
                ?? throw new InvalidOperationException("active locale key map is unavailable");
            if (!(bool)containsKey.Invoke(map, new object[] { key }))
            {
                localeItem.SetValue(root, textConstructor.Invoke(new object[] { english[key] }), new object[] { key });
                if (!(bool)containsKey.Invoke(map, new object[] { key }))
                    throw new InvalidOperationException("locale key write was discarded: " + key);
                var inserted = localeItem.GetValue(root, new object[] { key });
                if (inserted == null || (string)localeValue.GetValue(inserted) != english[key])
                    throw new InvalidOperationException("locale text write was discarded: " + key);
            }
            var value = localeItem.GetValue(root, new object[] { key });
            string template = value == null ? null : (string)localeValue.GetValue(value);
            if (string.IsNullOrWhiteSpace(template))
                throw new InvalidOperationException("locale text is empty: " + key);
            return string.Format(CultureInfo.InvariantCulture, template, StunClub.ExtraPurePercent);
        }
    }
}
