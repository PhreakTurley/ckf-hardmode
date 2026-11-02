// Feed the verified Workshop payloads to the game's own mod loader. No SQL
// connection, save reader or database writer is implemented here.
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Security.Cryptography;
using System.Text.Json;
using BepInEx;
using HarmonyLib;

namespace CKFHardMode
{
    internal static class BundledRebalances
    {
        internal const string DirectoryName = "ckf.hardmode.rebalances";
        private sealed record Pack(string Slice, string Folder, string Id, string WorkshopId);
        private static readonly Pack[] Packs = {
            new("PlayerRebalance", "player", "18446744073709551001", "3814427009"),
            new("EnemyRebalance", "enemy", "18446744073709551002", "3829942905")
        };
        private static readonly List<Pack> enabled = new();
        private static Type itemType, steamType;
        private static ConstructorInfo steamConstructor;
        private static bool ready;
        private static readonly HashSet<string> reported = new();

        internal static void Init(Harmony harmony)
        {
            foreach (var pack in Packs)
            {
                if (!Slices.On(pack.Slice))
                {
                    Plugin.Log.LogInfo(Slices.OffBecause(pack.Slice, "no bundled native data is supplied."));
                    continue;
                }
                VerifyPack(Path.Combine(Paths.ConfigPath, DirectoryName, pack.Folder));
                enabled.Add(pack);
            }
            if (enabled.Count == 0) return;
            var manager = RequireType("RPG.Core.ModSystem.ModManager");
            itemType = RequireType("RPG.Core.ModSystem.ModItem");
            steamType = RequireType("RPG.Core.ModSystem.ModItemSteamData");
            steamConstructor = steamType.GetConstructors().Single(c => c.GetParameters().Length == 5);
            // CoreRPG_v1 metadata: ModManager.GetSortedModsList(),
            // WriteToModsListFile(List<ModItem>), ModItem's parameterless
            // constructor, Id/IsSteamValid/Sort/ItemData and private IsActive
            // setter; ModItemSteamData(PublishedFileId_t,uint,string,ulong,uint).
            harmony.Patch(AccessTools.Method(manager, "GetSortedModsList"),
                postfix: new HarmonyMethod(typeof(BundledRebalances), nameof(AfterList)));
            harmony.Patch(AccessTools.Method(manager, "WriteToModsListFile"),
                prefix: new HarmonyMethod(typeof(BundledRebalances), nameof(BeforeWriteList)));
            ready = true;
            Plugin.Log.LogInfo("BundledRebalances: native mod-list hooks ready for "
                + string.Join(", ", enabled.Select(p => p.Slice))
                + ". Payload loading is reported separately by the game.");
        }

        internal static void VerifyPack(string folder)
        {
            using var document = JsonDocument.Parse(File.ReadAllBytes(Path.Combine(folder, "receipt.json")));
            var root = document.RootElement;
            if (root.GetProperty("format").GetInt32() != 1
                || root.GetProperty("verification").GetProperty("status").GetString() != "PASS")
                throw new InvalidDataException("Unknown bundled rebalance receipt: " + folder);
            foreach (var name in new[] { "data.sql", "en-US.json" })
            {
                var bytes = File.ReadAllBytes(Path.Combine(folder, "_data", name));
                var hash = Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
                if (hash != root.GetProperty("files").GetProperty(name).GetString())
                    throw new InvalidDataException("Bundled payload hash mismatch: " + folder + "/" + name);
            }
        }

        private static void AfterList(object __result)
        {
            if (!ready || __result == null) return;
            try
            {
                foreach (var pack in enabled)
                {
                    var rows = Items(__result).ToList();
                    if (rows.Any(row => (string)Get(row, "Id") == pack.Id)) continue;
                    if (rows.Any(row => (string)Get(row, "Id") == pack.WorkshopId && (bool)Get(row, "IsActive")))
                        throw new InvalidOperationException("Disable Workshop item " + pack.WorkshopId
                            + " before using bundled " + pack.Slice + "; overlapping packages were refused.");
                    var folder = Path.Combine(Paths.ConfigPath, DirectoryName, pack.Folder);
                    VerifyPack(folder);
                    var parameters = steamConstructor.GetParameters();
                    var fileId = Activator.CreateInstance(parameters[0].ParameterType, ulong.Parse(pack.Id));
                    var data = steamConstructor.Invoke(new object[] { fileId, (uint)5, folder, (ulong)0, (uint)0 });
                    var item = Activator.CreateInstance(itemType);
                    Set(item, "Id", pack.Id);
                    Set(item, "Sort", int.MaxValue - Array.IndexOf(Packs, pack));
                    Set(item, "ItemData", data);
                    Set(item, "IsSteamValid", true);
                    Set(item, "IsActive", true);
                    if (!(bool)Get(item, "IsActive") || (string)Get(item, "FolderPath") != folder)
                        throw new InvalidOperationException("Native mod item did not retain activation or folder: " + pack.Slice);
                    __result.GetType().GetMethod("Add").Invoke(__result, new[] { item });
                    if (reported.Add(pack.Id)) Plugin.Log.LogInfo("BundledRebalances: supplied active "
                        + pack.Slice + " to native mod list from " + folder);
                }
            }
            catch (Exception e)
            {
                // Do not leave half of the combined package supplied after a failure.
                RemoveBundled(__result);
                ready = false;
                Plugin.Log.LogError("BundledRebalances: native handoff refused; no bundled data supplied: " + e);
            }
        }

        // Synthetic entries are process-local. Applying a player's Mods menu
        // must not persist them into the game's Steam subscription selection.
        private static void BeforeWriteList(ref object __0)
        {
            if (__0 == null) return;
            var rows = Items(__0).ToList();
            if (!rows.Any(row => IsBundled((string)Get(row, "Id")))) return;
            var copy = Activator.CreateInstance(__0.GetType());
            var add = copy.GetType().GetMethod("Add");
            foreach (var row in rows)
                if (!IsBundled((string)Get(row, "Id"))) add.Invoke(copy, new[] { row });
            __0 = copy;
        }

        private static bool IsBundled(string id) => Packs.Any(pack => pack.Id == id);
        private static void RemoveBundled(object list)
        {
            var remove = list.GetType().GetMethod("RemoveAt");
            var rows = Items(list).ToList();
            for (int i = rows.Count - 1; i >= 0; i--)
                if (IsBundled((string)Get(rows[i], "Id"))) remove.Invoke(list, new object[] { i });
        }
        private static IEnumerable<object> Items(object list)
        {
            int count = (int)Get(list, "Count");
            var at = list.GetType().GetProperty("Item");
            for (int i = 0; i < count; i++) yield return at.GetValue(list, new object[] { i });
        }
        private static object Get(object value, string name) => value.GetType().GetProperty(name).GetValue(value);
        private static void Set(object value, string name, object data) => value.GetType().GetProperty(name).SetValue(value, data);
        private static Type RequireType(string name) => AccessTools.TypeByName(name)
            ?? throw new TypeLoadException(name);
    }
}
