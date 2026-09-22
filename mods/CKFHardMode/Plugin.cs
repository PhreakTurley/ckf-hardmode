// CKF Hard Mode — custom difficulty beyond the in-game sliders.
//
// SCOPE. This plugin changes how the game plays and does nothing else.
// Settings subsystems, in the order Load() initialises them (that sequence is
// the canonical list). Each reads its own settings file,
// ckf.hardmode.d/<file>.json, through ConfigDoc:
//
//   ModelRules    the rule engine: applies every overlay and lever sheet in
//                 ckf.hardmode.d and inserts cloned rows (modelrules.json)
//   SelfCheck     the regression suite (a diagnostic; the one switch off by
//                 default), initialised beside ModelRules because it reads
//                 the database types ModelRules resolved (selfcheck.json)
//   PowerLevel    lift the mission Power Level ceiling of 10 (powerlevel.json)
//   Progression   replace the Team Power Level a mission awards (teampl.json)
//   Fatigue       tire mercs out across missions, using the game's own
//                 temporary traits (fatigue.json)
//   Elapse        charge the crew when a mission's window closes unplayed:
//                 credits off the balance, Stress onto linked mercs
//                 (elapse.json)
//   MissionRewards  adjust payment, XP and Team PL per mission type
//                 (missions.json)
//   RewardCurve   replace the base reward-per-power-level curve
//                 (rewardcurve.json)
//   Difficulty    widen the custom-difficulty sliders past their stock
//                 bounds so values are set on the in-game sliders
//                 (difficulty.json)
//
// The content slices (lever sheets and talent overlays) have no Init of their
// own; Overlays.Load expands them while ModelRules loads.
//
// SWITCHES. ckf.hardmode.cfg holds [General] Enabled plus one [Slices] key per
// slice. Slices.Init binds them all and is the only place a gate is read. A
// gate lives in the .cfg rather than in the file it gates, so a syntax error
// in a settings file cannot take its switch with it. [General] Enabled keeps
// its own section and name, so an older .cfg still turns the mod off.
//
// FILES. The mod's config files ship as loose files in the release zip, under
// BepInEx\config. They are not embedded in this DLL, so retuning the mod is a
// file edit and a re-run of scripts/make_release.py, with no rebuild.
// Defaults.Install only reports which of them arrived.
//
// Fatigue and Elapse are the only subsystems that WRITE to the save.
// Everything else reads the game and adjusts what it reads. Fatigue inserts
// and deletes GameCharacterTrait rows, which the game then expires by itself;
// Elapse spends credits through the engine's own SpendCredits and updates a
// merc's NegativeTraitValue. Their switches default to on, so an install
// with default switches writes to the save from the first mission.
//
// Everything that only READS the game (column dumps, row logs, table sweeps,
// method traces, member lists) lives in CKF Data Dump, a separate assembly
// with its own GUID and config file. Neither plugin depends on the other. You
// want balance changes on every launch and a full data dump rarely, so the
// dump's hooks and load time are not carried here.
//
// DIFFICULTY. The game already has a full custom-difficulty system
// (WindowCustomizeDifficulty) whose values are clamped by Min/Max pairs on
// RPG.Database.Models.GameDifficultyModel. Those bounds are ordinary settable
// properties, and they are STATIC:
//
//   PROP Single PowerLevelScalarMin get/set     PROP Single PowerLevelScalarMax get/set
//   PROP Single BasePowerLevelOffsetMin get/set PROP Single BasePowerLevelOffsetMax get/set
//
// A materialized GameDifficultyModel row carries no bound among its instance
// properties; they are limits of the difficulty system, one set for the whole
// game, so widening is a one-shot at load. A member scan that omits
// BindingFlags.Static does not see them.
//
// So the sliders are given a longer run (sliderRangeMultiplier, the only key
// in difficulty.json), and the in-game window is the only place a value is
// set. PowerLevelCap reads whatever ends up on the model, and "PowerLevel"
// does the one thing this cannot: lift the ceiling of 10 the game clamps its
// own result to.
//
// Because the values land on the model the game itself uses, everything
// downstream (power level calculation, writing into the save database) stays
// consistent. We never touch the encrypted database; the game writes it.
//
// Members are resolved reflectively, so this compiles without exact
// signatures and tolerates the game renaming things between patches.

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
        public const string PluginVersion = "4.1.0";

        internal static new ManualLogSource Log;
        internal static ConfigEntry<bool> Enabled;

        /// <summary>"sliderRangeMultiplier" from difficulty.json. 1.0 means
        /// "leave the stock ranges alone", which is also what a settings file
        /// that could not be read leaves behind.</summary>
        internal static double SliderRange = 1.0;

        // The whole of difficulty.json: one key.
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
            // scripts/gen_binds.py generates from schema/*.schema.json. The binds
            // carry no descriptions: the key prose lives in
            // docs/config-reference.md. Every declared key is bound here,
            // through Slices.Init, because BepInEx only writes a .cfg line for a
            // key that something bound.
            //
            // ORDER. This is ABOVE the bail-out below on purpose. Binding under
            // it would mean an install with Enabled = false never gets its
            // [Slices] lines written, so the config editor would have nothing to
            // show and check_schema.py would report every one of them MISSING.
            // [General] Enabled is a bind because it has to work when no
            // settings file exists at all, and BepInEx writes ckf.hardmode.cfg
            // whether or not anything else on disk is intact.
            Enabled = Slices.Init(Config);

            // ORDER MATTERS. This bail-out has to come before any subsystem is
            // initialised, or Enabled = false would still let ModelRules
            // rewrite rows and PowerLevelCap overwrite calculations.
            //
            // A master switch that could NOT BE READ is not a master switch set
            // to false (AGENTS.md). Slices.Init reports the bind failure by
            // name at Error; this runs on rather than turning the mod off on an
            // answer nobody got, which would look identical to the player having
            // turned it off themselves.
            if (Enabled == null)
            {
                Log.LogError("Plugin: [General] Enabled could not be bound — see the error "
                    + "above. That is NOT the same as it being false, so the mod RUNS this "
                    + "launch. If you meant to turn it off, fix ckf.hardmode.cfg and relaunch.");
            }
            else if (!Enabled.Value)
            {
                Log.LogInfo("Disabled via config; nothing patched. The game runs unmodified.");
                return;
            }

            // COUNT the config files before anything reads them. This writes
            // nothing: the files arrive with the release zip, and all this
            // call does is say which of them are on disk, so a partial
            // extraction is a named error at the top of the log rather than
            // one subsystem at a time reporting that it has nothing to read.
            //
            // ORDER. Above ConfigDoc.Init(), so the count is the first thing in
            // the log and a reader knows whether the files about to be
            // complained about are even there; and below the master-switch
            // bail-out, because a disabled mod has nothing to check.
            Defaults.Install();

            // Read the settings files before any subsystem asks for one, so
            // ConfigDoc's summary line and stray-key Errors land at the TOP of
            // the log, and so the stray-key guard runs even on a launch where
            // every settings subsystem is switched off. A guard that only runs
            // when someone asks is one that can go quiet (AGENTS.md).
            ConfigDoc.Init();

            // BOTH LAYOUTS PRESENT IS A REFUSAL, NOT A PREFERENCE. ConfigDoc
            // has already logged the Error naming both layouts and what to do;
            // this is the half that makes "nothing is applied" true. It returns
            // ABOVE ModelRules.Init and the difficulty hook, so no rule is
            // compiled, no row is edited and no slider bound is widened.
            //
            // It returns BELOW Slices.Init for the same reason Slices.Init sits
            // above the master-switch bail-out: BepInEx writes
            // ckf.hardmode.cfg only from the keys something bound.
            if (ConfigDoc.BothLayouts)
            {
                Log.LogError("Plugin: stopping here. The game runs UNMODIFIED this launch. "
                    + "See the ConfigDoc error above for which two layouts are on disk and "
                    + "what to do about it. Nothing was patched, no rule was compiled and no "
                    + "file was written or renamed.");
                return;
            }

            // Difficulty only. A null type must not `return` here: ModelRules
            // has no dependency on GameDifficultyModel, and returning would
            // leave the whole row-edit engine unloaded. The section that needs
            // the type is guarded on it below instead.
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

            // THE 4.0 LAYOUT HAS NO RULES FILE, AND THIS SAYS SO.
            //
            // ModelRules.Init uses this path for two things: LoadRules reads
            // rules from it, and Overlays.Load is handed
            // GetDirectoryName(rulesPath) + "ckf.hardmode.d". The second is why
            // the variable still exists: the overlay directory is the whole
            // rule set, and it is derived the same way whether or not the file
            // is there.
            //
            // "Not there" is the expected answer and is stated at Info, every
            // launch, because an instrument that speaks only on failure has
            // gone quiet (AGENTS.md). "There" is an Error: a rules file is read
            // FIRST and its rules apply BEFORE the sheets, so any rule in it
            // that is not a plain `set` (multiply, add, clamp, clone) lands on
            // top of the sheet that replaced it.
            //
            // NEITHER BRANCH IS "COULD NOT LOOK". An exception out of
            // File.Exists is its own third outcome, reported as itself.
            var rulesPath = System.IO.Path.Combine(Paths.ConfigPath, "ckf.hardmode.rules.json");
            try
            {
                if (System.IO.File.Exists(rulesPath))
                {
                    Log.LogError($"ModelRules: {rulesPath} IS ON DISK. The 4.0 layout does "
                        + "not have this file -- its rules live in " + ConfigDoc.DirName
                        + " now. It will be read "
                        + "FIRST, before every overlay and every lever sheet, so anything in "
                        + "it that is not a plain `set` applies ON TOP of the sheet that "
                        + "replaced it. If you restored it deliberately, the rules it "
                        + "duplicates are live twice; if you did not, delete it. The rule "
                        + "count it contributes is reported on ModelRules' own line below.");
                }
                else
                {
                    Log.LogInfo($"ModelRules: no {System.IO.Path.GetFileName(rulesPath)} in "
                        + $"{Paths.ConfigPath}. THIS IS THE 4.0 LAYOUT AND IS EXPECTED -- the "
                        + "rule set is the files in " + ConfigDoc.DirName + ". Nothing is "
                        + "missing. The rule plan below is the whole of it.");
                }
            }
            catch (Exception e)
            {
                // Not "absent": nobody could look. Its own outcome, so a config
                // directory this process cannot read never reads as the
                // expected 4.0 answer.
                Log.LogError($"ModelRules: could not tell whether {rulesPath} exists: "
                    + $"{e.GetType().Name}: {e.Message}. Neither \"the 4.0 layout has no "
                    + "rules file\" nor \"a rules file came back\" has been established "
                    + "this launch.");
            }
            try
            {
                // Init checks its own slice gate and settings file and returns
                // without hooking anything when it is off or unreadable, so
                // there is no switch to test out here.
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

            // Independent of the ModelRules switch, so this subsystem's own
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

            // Every slice has a [Slices] gate, and this is Difficulty's.
            if (!Slices.On("Difficulty"))
            {
                Log.LogInfo(Slices.OffBecause("Difficulty",
                    "the custom-difficulty sliders keep their stock bounds this launch. "
                    + "Nothing is patched."));
                return;
            }

            // The one key difficulty.json has. A file that could not be read
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
        // Static as well as instance. The slider bounds are STATIC properties:
        // a materialized GameDifficultyModel row has no bound among its
        // instance properties. They are limits of the difficulty system, not
        // per-save data, so there is one set of them for the whole game.
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
        // Two separate traps here.
        //
        // A flat GetProperties returns non-public members only for the type
        // itself, so anything declared further up is invisible. AccessTools
        // walks the hierarchy asking each level for its DECLARED members, and
        // so must this. This ORM inherits heavily (CoreGameDataModel keeps
        // set_PowerLevel on CoreGameDataModelBase), so the walk is mandatory.
        //
        // The flags must include Static, because the bounds are static.
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
