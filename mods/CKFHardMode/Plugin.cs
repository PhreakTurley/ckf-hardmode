// CKF Hard Mode — custom difficulty beyond the in-game sliders.
//
// SCOPE. This plugin changes how the game plays and does nothing else.
// Eight subsystems, in the order Load() initialises them — that sequence is
// the canonical list. Each name is its section in ckf.hardmode.json, which
// since 3.0 is where every setting except the master switch lives:
//
//   "modelrules"   apply declarative row edits from ckf.hardmode.rules.json
//   "selfcheck"    the regression suite (a diagnostic; the one thing off by
//                  default), initialised beside ModelRules because it reads
//                  the database types ModelRules resolved
//   "powerlevel"   lift the mission Power Level ceiling of 10
//   "teampl"       scale the Team Power Level a mission awards
//   "fatigue"      tire mercs out across missions, using the game's own
//                  temporary traits
//   "elapse"       charge the crew when a mission's window closes unplayed:
//                  credits off the balance, Stress onto linked mercs
//   "missions"     adjust payment, XP and Team PL per mission type
//   "rewardcurve"  replace the base reward-per-power-level curve
//   "difficulty"   widen the custom-difficulty sliders past their stock
//                  bounds so the values are set on the in-game sliders
//
// The mod's own files SHIP AS LOOSE FILES IN THE RELEASE ZIP, under
// BepInEx\config: the config document, ckf.hardmode.rules.json,
// ckf.hardmode.selfcheck.csv, ckf.hardmode.cfg and the four files of
// ckf.hardmode.d/. Extracting the zip is what puts them there, and
// Defaults.Install only reports which of them arrived.
//
// CORRECTION, 2026-09-07. Until this date they were EmbeddedResources in this
// DLL and Defaults.Install wrote any that were absent, so the DLL alone was a
// complete mod. That coupled every tuning change to a rebuild — an edited
// default and no `dotnet build` shipped a zip whose numbers were not the ones
// in the repository, which is the failure make_release.py's check_embedded
// existed to catch. The files are the release's now, and retuning the mod is a
// file edit and a re-run of scripts/make_release.py.
//
// ckf.hardmode.cfg has exactly one key left, [General] Enabled. It stays a
// BepInEx bind because it is the switch that has to work when the merged
// document does not exist at all. One consequence worth stating: a syntax
// error anywhere in ckf.hardmode.json now costs every subsystem its settings
// AND its switch, where in 2.x the switch came from the cfg and survived.
// ConfigDoc says so at Error, and each subsystem says which of the two it is.
//
// [Fatigue] and [Elapse] are the odd ones out and worth flagging here: they
// are the only subsystems that WRITE to the save. Everything else reads the
// game and adjusts what it reads. Fatigue inserts and deletes
// GameCharacterTrait rows, which the game then expires by itself; Elapse
// spends credits through the engine's own SpendCredits and updates a merc's
// NegativeTraitValue. Both now ship ON — David's ruling 2026-08-31 that every
// feature switch defaults true — so a fresh install writes to the save from the
// first mission. The numbers they write come from the "fatigue" and "elapse"
// sections of ckf.hardmode.json.
//
// Everything that only READ the game — dumping a table's columns, logging
// every row, sweeping tables into CSV, tracing a method's arguments, listing a
// type's members — has moved to CKF Data Dump. That is a separate assembly
// with its own GUID and its own config file. It shares no code with this one,
// neither declares a dependency on the other, and either works alone.
//
// The reason is cost asymmetry. You want balance changes on every launch and a
// full data dump roughly never. Bundling them meant carrying the dump's hooks
// and load time forever, and it is why twelve tables passed for a complete
// capture across a dozen runs: the dump only ever reached tables that had been
// named by hand, twice.
//
// The game already has a full custom-difficulty system (WindowCustomizeDifficulty)
// whose values are clamped by Min/Max pairs on RPG.Database.Models.GameDifficultyModel.
// The original worry was that those clamps might be compile-time constants inlined
// by IL2CPP, and therefore unpatchable, so this plugin let the game configure
// difficulty normally and then overwrote the resulting values afterwards.
//
// The member dump settled that: they are ordinary settable properties.
//
//   PROP Single PowerLevelScalarMin get/set     PROP Single PowerLevelScalarMax get/set
//   PROP Single BasePowerLevelOffsetMin get/set PROP Single BasePowerLevelOffsetMax get/set
//
// They are also STATIC, which took two failed runs to notice. Run28 dumped a
// materialized GameDifficultyModel row: 66 instance properties, not one of them
// a bound. They are limits of the difficulty system rather than per-save data,
// so there is a single set for the whole game and widening is a one-shot at
// load. The reason the earlier member dump showed them at all is that it passed
// BindingFlags.Static and the scan did not. (That member dump now lives in the
// CKF Data Dump plugin, under [Diagnostics] DumpMembers.)
//
// So the sliders can simply be given a longer run, which is what
// SliderRangeMultiplier does, and it is the only key this section has left.
//
// The "difficulty" section no longer carries copies of the game's own knobs
// either. Widening the Min/Max bounds is all it does, so the in-game
// custom-difficulty window is the one and only place a value is set.
// PowerLevelCap reads whatever ends up on the model, so it picks up whatever
// the slider set, and "powerlevel" is left doing the one thing this section
// cannot: lifting the ceiling of 10 that the game clamps its own result to.
//
// Because the values land on the model the game itself uses, everything downstream
// (power level calculation, writing into the save database) stays consistent. We
// never touch the encrypted database; the game writes it for us.
//
// Members are resolved reflectively, so this compiles without needing exact
// signatures up front and tolerates the game renaming things between patches.

using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Reflection;
using System.Text.Json;
using System.Text.Json.Serialization;
using BepInEx;
using BepInEx.Configuration;
using BepInEx.Logging;
using BepInEx.Unity.IL2CPP;
using HarmonyLib;

namespace CKFHardMode
{
    [BepInPlugin(PluginGuid, PluginName, PluginVersion)]
    public class Plugin : BasePlugin
    {
        public const string PluginGuid = "ckf.hardmode";
        public const string PluginName = "CKF Hard Mode";
        public const string PluginVersion = "3.0.0";

        internal static new ManualLogSource Log;
        internal static ConfigEntry<bool> Enabled;

        /// <summary>[Difficulty] SliderRangeMultiplier, which since 3.0 is
        /// "sliderRangeMultiplier" in the "difficulty" section of
        /// ckf.hardmode.json. 1.0 means "leave the stock ranges alone", which
        /// is also what a section that could not be read leaves behind.
        /// </summary>
        internal static double SliderRange = 1.0;

        // The whole of the "difficulty" section: one key.
        private sealed class DifficultyOptions : ConfigDoc.IHasUnknownKeys
        {
            [JsonPropertyName("sliderRangeMultiplier")]
            public double SliderRangeMultiplier { get; set; } = 3.0;
            [JsonExtensionData] public Dictionary<string, JsonElement> Unknown { get; set; }
            public Dictionary<string, JsonElement> UnknownKeys { get { return Unknown; } }
        }

        internal const string DifficultyTypeName = "RPG.Database.Models.GameDifficultyModel";
        private static readonly string[] HookMethods = { "ReconfigureDifficulty", "ConfigureDefaults" };

        public override void Load()
        {
            Log = base.Log;

            // Section, key, type and default come from Plugin.Binds.g.cs, which
            // scripts/gen_binds.py generates from schema/*.schema.json. The
            // descriptions these calls used to carry are gone on purpose: they
            // were BepInEx's source for the "## " prose in ckf.hardmode.cfg, and
            // that prose now lives in docs/config-reference.md (gui-plan.md 3.2).
            //
            // 3.0: this is the ONLY bind. The other 21 keys are sections of
            // ckf.hardmode.json, read below. This one stays a bind because it
            // is the switch that has to work when that document does not exist
            // at all — BepInEx owns ckf.hardmode.cfg and writes it whether or
            // not anything else on disk is intact.
            Enabled = Binds.Bind<bool>(Config, "General", "Enabled");

            // ORDER MATTERS. This bail-out has to come before any subsystem is
            // initialised. It used to sit underneath, which meant Enabled =
            // false still let ModelRules rewrite every row and PowerLevelCap
            // overwrite every calculation — the master switch turned off the
            // [Difficulty] knobs and nothing else.
            if (!Enabled.Value)
            {
                Log.LogInfo("Disabled via config; nothing patched. The game runs unmodified.");
                return;
            }

            // COUNT the config files before anything reads them. This writes
            // nothing: the eight files arrive with the release zip, and all
            // this call does is say which of them are on disk, so a partial
            // extraction is a named error at the top of the log rather than
            // one subsystem at a time reporting that it has nothing to read.
            //
            // ORDER. Above ConfigDoc.Init(), so the count is the first thing in
            // the log and a reader knows whether the document it is about to
            // complain about is even there; and below the master-switch
            // bail-out, because a disabled mod has nothing to check.
            Defaults.Install();

            // Read ckf.hardmode.json before any subsystem asks for a section,
            // so its summary line and its stray-key Errors land at the TOP of
            // the log rather than wherever the first reader happens to be — and
            // so the stray-key guard runs even on a launch where every
            // subsystem that reads the document is switched off. AGENTS.md §3:
            // the guard has to be able to produce a row, and a guard that only
            // runs when someone asks is one that can go quiet.
            ConfigDoc.Init();

            // Every subsystem's settings, including its switch, now come from
            // that document. [ModelRules] Enabled used to be bound and read
            // ABOVE this call; ModelRules.Init reads it out of the "modelrules"
            // section itself, which is why it can no longer be read too early.

            // [Difficulty] only. This used to `return` on a null type, which
            // took the whole plugin down with it: ModelRules has no dependency
            // on GameDifficultyModel, and a failure to resolve one type left the
            // entire row-edit engine unloaded with nothing in the log saying so.
            // The section that needs the type is guarded on it below instead.
            var type = AccessTools.TypeByName(DifficultyTypeName);
            if (type == null)
            {
                Log.LogError($"Could not resolve {DifficultyTypeName}. SKIPPED: the "
                    + "\"difficulty\" section — the custom-difficulty sliders keep their stock "
                    + "bounds this launch. Every other subsystem still runs.");
                Log.LogError("Has the game updated, or did interop generation not finish? " +
                             "Check BepInEx/interop/ contains CoreRPG_v1.dll.");
            }

            var harmonyEarly = new Harmony(PluginGuid + ".models");
            var rulesPath = System.IO.Path.Combine(Paths.ConfigPath, "ckf.hardmode.rules.json");
            try
            {
                // Init reads the "modelrules" section itself and returns without
                // hooking anything when it is off or unreadable, so there is no
                // switch to test out here any more. It used to be tested here,
                // from a bind read at the top of this method — above
                // ConfigDoc.Init() — which is exactly the read that could not
                // survive the move.
                ModelRules.Init(harmonyEarly, rulesPath);
            }
            catch (Exception e)
            {
                // FAIL SAFE, not fail partway. Init installs the row postfix
                // on every hooked materializer before it builds the plans and
                // hands the clone rules to RowClone, so a throw in between
                // would leave ordinary rules firing while 'set' rules point
                // at clone ids nothing serves — the mission-hang shape
                // RowClone.cs describes, reached through the error path.
                //
                // The patches are DISABLED rather than removed. Removing
                // them would mean unpatching a Harmony instance mid-failure;
                // the flag is the thing this source can guarantee, and it is
                // checked at the top of every entry point ModelRules and
                // RowClone install, so the result is the same: nothing they
                // hooked does anything for the rest of the launch.
                Log.LogError($"ModelRules failed to initialise: {e}");
                ModelRules.Halt();
                Log.LogError("ModelRules: initialisation stopped partway, so the row-edit "
                    + "engine is DISABLED for this launch. Its patches are still installed "
                    + "and are now inert — every one of them returns without doing anything, "
                    + "so no rule fires and no clone is served, and the game's data is "
                    + "unmodified. The rest of the plugin still runs. Fix the error above and "
                    + "relaunch.");
            }

            // Independent of the "modelrules" switch, so this subsystem's own
            // setting is honoured on every launch. It is handed
            // ModelRules.ResolvedDbs, which is empty when ModelRules did not
            // run — and SelfCheck says so loudly rather than waiting.
            //
            // Nothing to check against a halted engine either: the rules were
            // not applied, and the hooks that would hand over a database
            // instance now return immediately. Hand it nothing, so it says so.
            try
            {
                SelfCheck.Init(Paths.ConfigPath,
                               ModelRules.Halted ? new List<Type>() : ModelRules.ResolvedDbs);
            }
            catch (Exception e) { Log.LogError($"SelfCheck failed to initialise: {e}"); }

            try
            {
                PowerLevelCap.Init(new Harmony(PluginGuid + ".powerlevel"));
            }
            catch (Exception e) { Log.LogError($"PowerLevel failed to initialise: {e}"); }

            try
            {
                Progression.Init(new Harmony(PluginGuid + ".progression"));
            }
            catch (Exception e) { Log.LogError($"Progression failed to initialise: {e}"); }

            try
            {
                Fatigue.Init(new Harmony(PluginGuid + ".fatigue"));
            }
            catch (Exception e) { Log.LogError($"Fatigue failed to initialise: {e}"); }

            try
            {
                Elapse.Init(new Harmony(PluginGuid + ".elapse"));
            }
            catch (Exception e) { Log.LogError($"Elapse failed to initialise: {e}"); }

            try
            {
                MissionRewards.Init(new Harmony(PluginGuid + ".missionrewards"));
            }
            catch (Exception e)
            {
                Log.LogError($"MissionRewards failed to initialise: {e}");
            }

            try
            {
                RewardCurve.Init(new Harmony(PluginGuid + ".rewardcurve"));
            }
            catch (Exception e)
            {
                Log.LogError($"RewardCurve failed to initialise: {e}");
            }

            // ---- "difficulty" ------------------------------------------------
            //
            // Everything from here down needs the GameDifficultyModel type. When
            // it did not resolve, this section is skipped and the error above
            // says so; nothing else in the plugin depends on it.
            if (type == null) return;

            // The one key this section has. A section that could not be read
            // leaves SliderRange at 1.0, and WidenSliders returns immediately
            // on anything at or below 1 — so the sliders keep their stock
            // ranges, which is the same thing the key itself means at 1.
            var diff = ConfigDoc.ReadSection<DifficultyOptions>(
                "Difficulty", ConfigDoc.Difficulty,
                "The custom-difficulty sliders keep their stock bounds this launch.");
            if (diff == null) return;
            SliderRange = diff.SliderRangeMultiplier;

            // The slider bounds are static, so this is a one-shot on the type
            // and it happens before anything can read them. The reconfigure and
            // materializer hooks below re-run it, which is idempotent because
            // every bound is computed from the stock values captured here.
            Patches.WidenSliders(type, null);

            var harmony = new Harmony(PluginGuid);
            var postfix = new HarmonyMethod(AccessTools.Method(typeof(Patches), nameof(Patches.AfterConfigure)));

            int patched = 0;
            foreach (var methodName in HookMethods)
            {
                foreach (var m in AccessTools.GetDeclaredMethods(type))
                {
                    if (m.Name != methodName || m.IsAbstract) continue;
                    try
                    {
                        harmony.Patch(m, postfix: postfix);
                        patched++;
                    }
                    catch (Exception e)
                    {
                        Log.LogWarning($"Could not patch {m.Name}: {e.Message}");
                    }
                }
            }

            // Widening the model the game reconfigures only helps if that is the
            // model the custom-difficulty window reads its bounds from. We have
            // no proof it is — the window may well materialize its own row. So
            // also widen every GameDifficultyModel that comes out of the
            // database, which costs nothing and covers the case.
            var widenPf = new HarmonyMethod(AccessTools.Method(typeof(Patches),
                nameof(Patches.AfterMaterializeDifficulty)));
            foreach (var dbName in new[] { "RPG.Database.DataDb", "RPG.Database.GameDb",
                                           "RPG.Database.CoreDb" })
            {
                var db = AccessTools.TypeByName(dbName);
                if (db == null) continue;
                foreach (var m in AccessTools.GetDeclaredMethods(db))
                {
                    if (m.IsAbstract || m.ReturnType == typeof(void)) continue;
                    if (m.Name.IndexOf("Difficulty", StringComparison.Ordinal) < 0) continue;
                    if (!m.Name.StartsWith("GetRow", StringComparison.Ordinal)
                        && !m.Name.StartsWith("Read", StringComparison.Ordinal)) continue;
                    try
                    {
                        harmony.Patch(m, postfix: widenPf);
                    }
                    catch (Exception e)
                    {
                        Log.LogWarning($"Difficulty: could not hook {m.Name}: {e.Message}");
                    }
                }
            }

            if (patched == 0)
                Log.LogError("No methods patched — the hook points may have been renamed. " +
                             "Point the CKF Data Dump plugin's [Diagnostics] DumpMembers at " +
                             DifficultyTypeName + " and compare the method list.");
        }
    }

    internal static class Patches
    {
        // Static as well as instance. The slider bounds turned out to be STATIC
        // properties — Run28 dumped a materialized GameDifficultyModel row and
        // it has 66 instance properties, not one of them a bound. They are
        // limits of the difficulty system, not per-save data, so there is one
        // set of them for the whole game.
        private const BindingFlags Any = BindingFlags.Public | BindingFlags.NonPublic
                                       | BindingFlags.Instance | BindingFlags.Static;

        // Stock bounds, captured the first time we see each slider. Everything is
        // computed from these rather than from the live values, because this
        // postfix runs on every reconfigure and multiplying the current maximum
        // would compound a little further every time.
        private static readonly Dictionary<string, double[]> StockRange =
            new Dictionary<string, double[]>(StringComparer.Ordinal);
        private static readonly HashSet<string> widenLogged =
            new HashSet<string>(StringComparer.Ordinal);

        // Runs after the game has configured difficulty. __instance is the
        // GameDifficultyModel the game will actually use.
        public static void AfterConfigure(object __instance)
        {
            if (__instance == null) return;

            // Widen first, then write. The values would land either way — this
            // postfix runs after the game's own clamping — but the custom
            // difficulty window reads these bounds to build its sliders, so
            // widening is what lets you set difficulty in-game rather than here.
            WidenSliders(__instance.GetType(), __instance);
        }

        // Every property on the type and its bases, declared level by level.
        //
        // Two separate traps here, one per failed run.
        //
        // Run27: a flat GetProperties returns non-public members only for the
        // type itself, so anything declared further up is invisible. AccessTools
        // walks the hierarchy asking each level for its DECLARED members, which
        // is why it had been resolving PowerLevelScalar since Run19 while this
        // scan saw nothing. This ORM inherits heavily — CoreGameDataModel keeps
        // set_PowerLevel on CoreGameDataModelBase — so the walk is mandatory.
        //
        // Run28: the flags left out Static, and the bounds ARE static. The row
        // dump settled it — 66 instance properties on a materialized
        // GameDifficultyModel and not one bound among them.
        private static Dictionary<string, PropertyInfo> AllProps(Type t)
        {
            var found = new Dictionary<string, PropertyInfo>(StringComparer.Ordinal);
            for (var cur = t; cur != null && cur != typeof(object); cur = cur.BaseType)
            {
                PropertyInfo[] declared;
                try { declared = cur.GetProperties(Any | BindingFlags.DeclaredOnly); }
                catch { continue; }
                foreach (var p in declared)
                    if (!found.ContainsKey(p.Name))    // nearest declaration wins
                        found[p.Name] = p;
            }
            return found;
        }

        // GameDifficultyModel pairs most settings with <Name>Min and <Name>Max
        // properties, and they are ordinary settable properties rather than the
        // consts we feared — so the in-game sliders can simply be given a longer
        // run. Pairs are discovered by name rather than listed, so a game update
        // that adds a setting gets the same treatment for free.
        //
        // The bounds are static, so `instance` may be null: passing the type
        // alone is enough, and that is how this runs once at load. An instance
        // is still accepted because nothing guarantees every future bound is
        // static, and a static property simply ignores the target.
        internal static void WidenSliders(Type t, object instance)
        {
            double m = Plugin.SliderRange;
            if (t == null || m <= 1.0) return;

            var props = AllProps(t);
            int widened = 0, pairs = 0;
            var notable = new List<string>();

            foreach (var maxProp in props.Values)
            {
                if (!maxProp.Name.EndsWith("Max", StringComparison.Ordinal)) continue;
                if (!IsNumeric(maxProp) || !maxProp.CanWrite || !maxProp.CanRead) continue;

                var stem = maxProp.Name.Substring(0, maxProp.Name.Length - 3);
                PropertyInfo minProp;
                if (!props.TryGetValue(stem + "Min", out minProp)) continue;
                if (!IsNumeric(minProp) || !minProp.CanWrite) continue;
                pairs++;

                // A static property ignores the target; an instance one needs
                // the real object, and without it there is nothing to read.
                object minTarget = IsStatic(minProp) ? null : instance;
                object maxTarget = IsStatic(maxProp) ? null : instance;
                if ((minTarget == null && !IsStatic(minProp))
                 || (maxTarget == null && !IsStatic(maxProp))) continue;

                try
                {
                    double[] stock;
                    var key = (t.FullName ?? t.Name) + "|" + stem;
                    if (!StockRange.TryGetValue(key, out stock))
                    {
                        stock = new[]
                        {
                            Convert.ToDouble(minProp.GetValue(minTarget), CultureInfo.InvariantCulture),
                            Convert.ToDouble(maxProp.GetValue(maxTarget), CultureInfo.InvariantCulture)
                        };
                        StockRange[key] = stock;
                    }

                    // A positive ceiling goes up; a negative floor goes further
                    // down; a positive floor comes down toward zero. A bound of
                    // exactly zero stays put — there is no sensible way to scale
                    // it, and moving it is how you get a scalar that can be set
                    // to a negative number.
                    double newMin = stock[0] < 0 ? stock[0] * m : stock[0] / m;
                    double newMax = stock[1] > 0 ? stock[1] * m : stock[1];

                    minProp.SetValue(minTarget, Convert.ChangeType(newMin, Underlying(minProp),
                                                                   CultureInfo.InvariantCulture));
                    maxProp.SetValue(maxTarget, Convert.ChangeType(newMax, Underlying(maxProp),
                                                                   CultureInfo.InvariantCulture));
                    widened++;

                    if (stem.IndexOf("PowerLevel", StringComparison.Ordinal) >= 0)
                        notable.Add($"{stem} [{stock[0]:0.##}, {stock[1]:0.##}] -> " +
                                    $"[{newMin:0.##}, {newMax:0.##}]");
                }
                catch (Exception e)
                {
                    Plugin.Log.LogWarning($"  {stem}: could not widen: {e.GetType().Name}: {e.Message}");
                }
            }

            // Once per distinct type, so hooking extra sources stays readable.
            if (widenLogged.Add(t.FullName ?? t.Name))
            {
                Plugin.Log.LogInfo($"Difficulty: {t.Name} — {props.Count} properties, " +
                    $"{pairs} Min/Max pair(s), widened {widened} by x{m}.");
                foreach (var n in notable) Plugin.Log.LogInfo($"  {n}");
                if (pairs == 0)
                    Plugin.Log.LogWarning($"Difficulty: no <Name>Min/<Name>Max pairs on " +
                        $"{t.FullName} — the in-game sliders will keep their stock ranges. " +
                        "Properties seen: " + string.Join(", ", props.Keys
                            .Where(n => !n.StartsWith("_", StringComparison.Ordinal)).Take(40)));
            }
        }

        // A GameDifficultyModel straight out of the database, before anything
        // has had a chance to read its bounds. Redundant while the bounds are
        // static, but it costs nothing and covers a future instance-level one.
        public static void AfterMaterializeDifficulty(object __result)
        {
            if (__result == null) return;
            var rt = __result.GetType();
            // Bulk readers hand back a list; scanning that is just noise.
            if (rt.Name.IndexOf("Difficulty", StringComparison.Ordinal) < 0) return;
            try { WidenSliders(rt, __result); }
            catch (Exception e)
            {
                Plugin.Log.LogWarning($"Difficulty: widening a materialized row failed: " +
                    $"{e.GetType().Name}: {e.Message}");
            }
        }

        private static bool IsStatic(PropertyInfo p)
        {
            var m = p.GetGetMethod(true) ?? p.GetSetMethod(true);
            return m != null && m.IsStatic;
        }

        private static bool IsNumeric(PropertyInfo p)
        {
            var u = Underlying(p);
            return u == typeof(float) || u == typeof(double)
                || u == typeof(int) || u == typeof(long);
        }

        private static Type Underlying(PropertyInfo p) =>
            Nullable.GetUnderlyingType(p.PropertyType) ?? p.PropertyType;
    }
}
