// Elapse — the mission elapse penalty.
//
// The design is docs/mission-elapse-penalty.md; this file is its implementation.
// When a mission's window closes unplayed, credits come off the balance and
// Stress goes onto mercs who had a reason to care about that contact. Nothing
// else. On by default as of 2.12.0. Every write below happens live; David's
// standing instruction of 2026-08-31 is to test that way (AGENTS.md §6).
//
// THIS SUBSYSTEM WRITES TO THE SAVE. Two write channels, both proven against a
// live save by CKFDataDump's WriteProbe before this was written:
//
//   Credits   SaveManager.SpendCredits(long, string) -> bool, inherited from
//             GameManagerBase. Run52 proved AddCredits on the same object; the
//             database row (UpdateGameData) is KNOWN BROKEN — Run49 saw it
//             revert on the next tick because the engine writes its own live
//             GameDataModel back over the row. The charge is capped to the
//             live balance first (David's ruling: a 400 fine against 300
//             credits takes 300), so SpendCredits returning false is only a
//             backstop, and a surprise worth reporting.
//   Stress    set GameCharacterModel.NegativeTraitValue, then
//             GameDb.UpdateGameCharacter(row). Run50/51: the Stress bar moved.
//             THE COLUMN NAMES LIE — `StressScore` is the DISCONTENT bar
//             (Run49). Spec §6.0. Do not "fix" this to StressScore.
//             THE ROW IS NOT THE AUTHORITY EITHER. Run55: every row write
//             read back correctly, and the roster panel kept showing the old
//             number — Midnight's 7 surfaced turns later, nobody else's at
//             all. SaveManager.playerCache holds a live PlayerModel per merc
//             whose CharacterModel is what the UI reads and what the engine
//             writes back. So the cached object is the AUTHORITY: it is
//             what `before` is read from, it is what the increase is added
//             to, and it is what is passed to UpdateGameCharacter. The row
//             is written too, as a write-through copy, and is only read when
//             there is no cached object to ask.
//             CORRECTION, 2.13.0: this header used to promise "a watch line
//             follows every written merc for a few ticks so drift between
//             cache and row is measured". That instrument was removed from
//             the code at some point before 2.12.0 and the sentence outlived
//             it. It did run: Log18 has its 42 samples, 7 writes over 6
//             mercs, every one `row N, cache N`. That is the evidence the
//             cache-only rule above rests on.
//
// HOW AN EXPIRY IS DETECTED. The game logs every expiry as a GameLogModel row
// with LogTypeId 202, stamped with the turn that was ENDING, and the postfix on
// SaveManager.ProcessTimelineToNextTurn reads GameTurn after it has advanced,
// so every row seen so far carried `turn - 1` (Runs 48-55, nine rows). Since
// 2.10.2 the stamp is recorded, not filtered on: a 202 row is an expiry when
// its Id is above the previous tick's highest, because the game moves mission
// deadlines on purpose and a row stamped anything else would otherwise be
// dropped silently. The 202 row carries a title and nothing else usable,
// and the GameMissionModel row is DELETED when the window closes (Run48,
// mission 114 gone between turns 1386 and 1387, no flag set on the way out).
// So every tick snapshots the board, and an expiry resolves against the
// PREVIOUS tick's snapshot — the last tick on which the mission was still
// there. One tick of history is exactly enough and there is none to spare.
//
// THE THREE RULES CARRIED OVER FROM Fatigue.cs, each of which cost a run:
//   1. Never store the GameDb. Reached off the SaveManager the hook hands us,
//      used inside the postfix, dropped. A cached instance that outlived its
//      moment is the Log7 mission hang.
//   2. [ThreadStatic] reentrant. Our reads and writes call GameDb methods on
//      a GameDb we hold a postfix on.
//   3. Swallow every exception. A postfix that throws surfaces inside the
//      game's own turn advance.
//
// REPLAY. There is no stored progress across sessions. Reloading to before an
// expiry and advancing again re-applies the penalty, which is the point of a
// mod that exists to stop the player dodging a consequence. The session-scoped
// double-fire guard (turn + title) covers a second postfix firing on the same
// tick; it is dropped, with the snapshot, on the (speculative, see Fatigue.cs)
// save-load postfix and on either of Tick's two discontinuity signals:
//   * the turn moved by something other than 0 or +1, and
//   * a COMPLETE game-log read whose highest row id is BELOW this session's
//     high-water mark. The mark only ever rises within a session, so a top row
//     id under it means the log table is not the one that was baselined.
// Correcting an earlier claim in this header: it is not "any turn
// discontinuity". Neither signal sees a reload onto the same turn or the next
// one whose GameLogModel ids are HIGHER than the mark — the turn looks
// continuous and the log looks like it merely grew — so when the save-load
// postfix is also missing, that reload is not detected at all and the stale
// snapshot and guard survive it. Dropping too little matters because Fatigue's
// in-memory guard blocking a genuine replay was the 2.9.2 bug and this must
// not repeat it. After a DETECTED reload the snapshot is stale for exactly one
// tick, so an expiry stamped on the tick right after a load is missed and
// logged as unmatched. The spec accepts that cost.
//
// DETERMINISM. Who takes the stress is seeded from (turn, mission) ^ salt,
// splitmix64 as in Fatigue.StableRoll with a different salt so the two
// subsystems' rolls do not correlate. Without it §3.2's replay behaviour is a
// slot machine.

using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text.Json;
using System.Text.Json.Serialization;
using BepInEx;
using HarmonyLib;

namespace CKFHardMode
{
    internal static class Elapse
    {
        // GameLogTypes.MissionExpire. _id_constants.csv; 20 rows in the
        // reference save, ActorId blank on all of them.
        private const long LogTypeMissionExpire = 202;

        private const string SaveManagerTypeName = "RPG.Core.SaveManager";
        private const string TurnMethodName = "ProcessTimelineToNextTurn";
        private const string GameManagementTypeName = "ViewModel_GameManagement";

        // Both text forms of the 202 row end with this. The mission's own
        // title precedes it, which is what keys the snapshot.
        private const string WindowClosedSuffix = " Window Closed";

        // GameCharacterTagModel.ActorId for an edge toward a contact.
        private const string ContactActorPrefix = "NID_";

        // ---- config ----------------------------------------------------------

        // Every block below carries a [JsonExtensionData] bag. System.Text.Json
        // drops a key no declared property claims, in silence: "enabeld": false
        // in the credits block left Enabled at its default of true and the
        // player who tried to switch the channel off kept being charged. The
        // bag collects those keys instead, and Load reports each one by name
        // and refuses the file. (.NET 8 has a serializer option that does this
        // in one line; this project targets net6.0, so the bags do it here.)
        //
        // Matching stays case-SENSITIVE: PropertyNameCaseInsensitive would make
        // "Enabled" and "ENABLED" work, which hides a different class of typo.
        // The file ships lowercase keys, so a key in the wrong case lands in
        // the bag and gets reported like any other unrecognised key.
        private sealed class TierBlock
        {
            [JsonPropertyName("patterns")]   public List<string> Patterns { get; set; }
            [JsonPropertyName("multiplier")] public double Multiplier { get; set; } = 1.0;
            [JsonExtensionData] public Dictionary<string, JsonElement> Unknown { get; set; }
        }

        private sealed class TiersBlock
        {
            [JsonPropertyName("soloHack")] public TierBlock SoloHack { get; set; }
            [JsonPropertyName("story")]    public TierBlock Story { get; set; }
            [JsonPropertyName("standard")] public TierBlock Standard { get; set; }
            [JsonExtensionData] public Dictionary<string, JsonElement> Unknown { get; set; }
        }

        private sealed class CreditsRow
        {
            [JsonPropertyName("minPowerLevel")] public long MinPowerLevel { get; set; }
            [JsonPropertyName("amount")]        public long Amount { get; set; }
            [JsonExtensionData] public Dictionary<string, JsonElement> Unknown { get; set; }
        }

        private sealed class CreditsBlock
        {
            [JsonPropertyName("enabled")]          public bool Enabled { get; set; } = true;
            [JsonPropertyName("percentOfBalance")] public double PercentOfBalance { get; set; }
            [JsonPropertyName("byPowerLevel")]     public List<CreditsRow> ByPowerLevel { get; set; }
            [JsonExtensionData] public Dictionary<string, JsonElement> Unknown { get; set; }
        }

        private sealed class StressRow
        {
            [JsonPropertyName("minPowerLevel")] public long MinPowerLevel { get; set; }
            [JsonPropertyName("mercCount")]     public long MercCount { get; set; }
            [JsonPropertyName("stressAmount")]  public long StressAmount { get; set; }
            [JsonExtensionData] public Dictionary<string, JsonElement> Unknown { get; set; }
        }

        private sealed class StressBlock
        {
            [JsonPropertyName("enabled")]             public bool Enabled { get; set; } = true;
            [JsonPropertyName("cap")]                 public long Cap { get; set; } = 10;
            [JsonPropertyName("fallbackToRandom")]    public bool FallbackToRandom { get; set; } = true;
            [JsonPropertyName("applyTierMultiplier")] public bool ApplyTierMultiplier { get; set; }
            // Only mercs the engine's own GameCharacterModel
            // .IsStatusSafehouseAliveAndActive() says are in the safehouse.
            // Run55 stressed Status 5 and Status 7 mercs; what those are is
            // not established, and a merc the roster does not show cannot
            // show a penalty.
            [JsonPropertyName("safehouseOnly")]       public bool SafehouseOnly { get; set; } = true;
            [JsonPropertyName("byPowerLevel")]        public List<StressRow> ByPowerLevel { get; set; }
            [JsonExtensionData] public Dictionary<string, JsonElement> Unknown { get; set; }
        }

        private sealed class Options
        {
            [JsonPropertyName("enabled")]    public bool Enabled { get; set; } = true;
            [JsonPropertyName("logFirst")]   public int LogFirst { get; set; } = 40;
            [JsonPropertyName("tiers")]      public TiersBlock Tiers { get; set; }
            [JsonPropertyName("credits")]    public CreditsBlock Credits { get; set; }
            [JsonPropertyName("stress")]     public StressBlock Stress { get; set; }
            [JsonPropertyName("seedSalt")]   public long SeedSalt { get; set; } = 1163084112;
            [JsonExtensionData] public Dictionary<string, JsonElement> Unknown { get; set; }
        }

        private static Options o;
        private static bool active;
        private static int logFirst;

        // ---- state -----------------------------------------------------------

        // Our own reads and writes call GameDb methods on a GameDb we hold a
        // postfix on. Same flag, same reason, as Fatigue and RowClone.
        [ThreadStatic] private static bool reentrant;

        // The previous tick's board, keyed by MissionTitle. The only copy of an
        // expired mission's columns that still exists when its 202 row appears.
        private sealed class Snap
        {
            public long Id, ContactId, PowerLevelUnscaled, PowerLevel, EndTurn;
            public string Title, MissionTypeId;
            // Columns that came back null or unconvertible on this row. A
            // mission recorded with any of these is refused at resolution
            // rather than charged as "contactless" or "PL 0".
            public string Unreadable;
        }

        private static Dictionary<string, Snap> previousSnapshot =
            new Dictionary<string, Snap>(StringComparer.Ordinal);
        private static long prevTurn = -1;

        // Highest GameLogModel.Id seen on a complete read. A 202 row above it
        // is new since the previous tick. -1 with logBaselined false until the
        // first complete read of the session.
        private static long maxLogId = -1;
        private static bool logBaselined;

        // turn + ":" + title. Keyed on the pair because two missions can expire
        // on one turn (reference save: minimum gap 1 turn).
        private static readonly HashSet<string> applied =
            new HashSet<string>(StringComparer.Ordinal);

        private static int expiriesSeen;

        // Every merc written this session is re-read for a few ticks
        // afterwards, from the row AND from the cached PlayerModel, so the
        // log shows whether the value held, drifted, or was spent by a limit
        // break. Run55 is why: the writes "took" by the row and the roster
        // panel disagreed for turns.
        private static bool warnedNoCache, warnedNoSafehousePredicate, warnedCacheMiskeyed;
        private static string lastExcluded = "";
        private static long ticks;

        // True once ForgetSession has run, so the first-tick instrument line
        // can say whether it is the process's first tick or the first after a
        // session reset. ForgetSession puts `ticks` back to 0 so that line is
        // emitted again for the tick that rebuilds the snapshot.
        private static bool sessionWasReset;

        // (model, column) pairs already warned about as unreadable.
        private static readonly HashSet<string> unreadableWarned =
            new HashSet<string>(StringComparer.Ordinal);

        // Log-once flags.
        private static bool warnedNoRelTypes, warnedNoLiveCredits;
        private static bool warnedUncappedCharge, warnedSpendNotBool;

        // ---- init ------------------------------------------------------------

        public static void Init(Harmony harmony)
        {
            // 3.0: one gate, not two. [Elapse] Enabled is gone from
            // ckf.hardmode.cfg and "enabled" in the "elapse" section is the
            // whole chain, so the file is read first and the switch is read out
            // of it. logFirst came the same way; it used to be bound above this
            // early return so BepInEx would keep writing the key into the cfg
            // on the disabled path, and a JSON key needs nothing done to it to
            // stay on disk.
            o = Load();
            if (o == null) return;                       // Load already said why

            if (!o.Enabled)
            {
                Plugin.Log.LogInfo("Elapse: \"enabled\": false in the \"" + ConfigDoc.Elapse
                                 + "\" section of " + ConfigDoc.FileName + " — no hook "
                                 + "installed, nothing written.");
                return;
            }
            logFirst = o.LogFirst;
            if (!Validate()) return;

            int patched = Patch(harmony, SaveManagerTypeName, TurnMethodName,
                                nameof(AfterProcessTimeline));
            if (patched == 0)
            {
                Plugin.Log.LogError($"Elapse: could not patch {SaveManagerTypeName}."
                    + $"{TurnMethodName}, which is the only hook this feature has. Nothing will "
                    + "happen. Point CKFDataDump's [Diagnostics] DumpMembers at "
                    + SaveManagerTypeName + " and compare.");
                return;
            }

            // Same speculative seam Fatigue patches, for the same reason: it is
            // the only pair of methods in the interop assembly that name loading
            // a save. Tick's own discontinuity signals cover most of what this
            // hook covers but not all of it, so it is not redundant — correcting
            // the claim that used to stand here.
            int loadHooks = Patch(harmony, GameManagementTypeName, "LoadGame", nameof(AfterLoadGame))
                          + Patch(harmony, GameManagementTypeName, "LoadGameSlot", nameof(AfterLoadGame));
            if (loadHooks == 0)
                Plugin.Log.LogWarning($"Elapse: could not patch {GameManagementTypeName}"
                    + ".LoadGame/LoadGameSlot. Tick still drops the board snapshot and the "
                    + "double-fire guard on two signals of its own: a turn that moves by other "
                    + "than 0 or +1, and a complete game-log read whose highest row id is below "
                    + "this session's high-water mark. What neither sees is a reload onto the same "
                    + "turn or the next one whose log row ids are HIGHER than that mark; without "
                    + "this hook that reload is not detected at all, and the previous tick's "
                    + "snapshot and double-fire keys are carried into the loaded save.");

            active = true;

            Plugin.Log.LogWarning("Elapse: ACTIVE, and this subsystem WRITES TO YOUR SAVE.");
        }

        // 3.0: the text comes from ConfigDoc — one merged document, one section
        // each — and everything below that is unchanged. Same JsonSerializer
        // call, same POCOs, same [JsonExtensionData] bags, same defaulting, same
        // error paths. `path` is only ever interpolated into a message, and now
        // reads `...\ckf.hardmode.json section "elapse"`.
        private static Options Load()
        {
            var path = ConfigDoc.Where(ConfigDoc.Elapse);
            try
            {
                var text = ConfigDoc.SectionText(ConfigDoc.Elapse);
                if (text == null)
                {
                    // AGENTS.md §3. "The section is not there" and "the document
                    // could not be read" are different findings: WhyNo says
                    // which, and the second is an Error, not a Warning.
                    // 3.0: this used to say "restore it from the mod's
                    // defaults" without saying where those were, because they
                    // did not exist. They are an EmbeddedResource now, so the
                    // instruction can be the actual one: delete the file and
                    // the next launch writes the shipped copy back.
                    var why = $"Elapse: {ConfigDoc.WhyNo(ConfigDoc.Elapse)}, so there are no "
                        + "amounts to work from. Doing nothing. To start again from the values "
                        + "the mod ships, delete BepInEx/config/" + ConfigDoc.FileName
                        + " and relaunch — it is written back whenever it is absent.";
                    if (ConfigDoc.CouldNotRead) Plugin.Log.LogError(why);
                    else Plugin.Log.LogWarning(why);
                    return null;
                }
                // PropertyNameCaseInsensitive is deliberately NOT set; see the
                // note on the config blocks above. Unrecognised keys are caught
                // after the parse, off the [JsonExtensionData] bags.
                var opts = new JsonSerializerOptions
                {
                    ReadCommentHandling = JsonCommentHandling.Skip,
                    AllowTrailingCommas = true
                };
                var f = JsonSerializer.Deserialize<Options>(text, opts);
                if (f == null)
                {
                    Plugin.Log.LogError($"Elapse: {path} parsed to nothing. Doing nothing.");
                    return null;
                }
                f.Tiers = f.Tiers ?? new TiersBlock();
                f.Tiers.SoloHack = f.Tiers.SoloHack ?? new TierBlock { Multiplier = 0.5 };
                f.Tiers.Story = f.Tiers.Story ?? new TierBlock { Multiplier = 1.5 };
                f.Tiers.Standard = f.Tiers.Standard ?? new TierBlock { Multiplier = 1.0 };
                f.Credits = f.Credits ?? new CreditsBlock();
                f.Credits.ByPowerLevel = f.Credits.ByPowerLevel ?? new List<CreditsRow>();
                f.Stress = f.Stress ?? new StressBlock();
                f.Stress.ByPowerLevel = f.Stress.ByPowerLevel ?? new List<StressRow>();

                // Checked after the defaulting above so the walk never has to
                // test for a missing block: a block the file did not have was
                // just created and its bag is null, which UnknownKeys skips.
                // Returning null is what turns the feature OFF — Init returns
                // immediately on a null, so no hook is installed and nothing
                // runs on the defaults the rejected file failed to override.
                var unknown = UnknownKeys(f);
                if (unknown.Count > 0)
                {
                    foreach (var line in unknown)
                        Plugin.Log.LogError($"Elapse: {path}: {line}");
                    Plugin.Log.LogError($"Elapse: {unknown.Count} unrecognised key(s) in {path}. "
                        + "Key names are case-sensitive and have to be spelled exactly as in the "
                        + "file shipped with the mod. Doing nothing — the feature is OFF and no "
                        + "hook is installed, rather than running on the built-in defaults with a "
                        + "key the player meant to set being ignored.");
                    return null;
                }
                return f;
            }
            catch (JsonException e)
            {
                // Malformed JSON: a missing brace, a bad number, a string where
                // a list belongs. Unrecognised KEYS do not arrive here — they
                // are collected into the extension-data bags and reported by
                // name above. e.Path locates the failure when it has one.
                Plugin.Log.LogError($"Elapse: {path} is not valid JSON: {e.Message}"
                    + (string.IsNullOrEmpty(e.Path) ? "" : $" (at {e.Path})")
                    + " Doing nothing — the feature is OFF and no hook is installed, rather than "
                    + "running on the built-in defaults.");
                return null;
            }
            catch (Exception e)
            {
                // Never throw past Init. A malformed sidecar turns the feature
                // off; it does not take the plugin with it.
                Plugin.Log.LogError($"Elapse: could not read {path}: {e.GetType().Name}: "
                                  + e.Message + ". Doing nothing.");
                return null;
            }
        }

        // One complaint line per key in the file that no declared property
        // claimed, naming the key and the block it was found in. The graph is
        // walked by hand rather than by reflection so the message can say "the
        // credits block" and "credits.byPowerLevel row 2" instead of a CLR type
        // name. An empty list means every key in the file was understood.
        private static List<string> UnknownKeys(Options f)
        {
            var bad = new List<string>();
            Note(bad, "the top level of the file", f.Unknown);

            Note(bad, "the tiers block", f.Tiers.Unknown);
            Note(bad, "the tiers.soloHack block", f.Tiers.SoloHack.Unknown);
            Note(bad, "the tiers.story block", f.Tiers.Story.Unknown);
            Note(bad, "the tiers.standard block", f.Tiers.Standard.Unknown);

            Note(bad, "the credits block", f.Credits.Unknown);
            for (int i = 0; i < f.Credits.ByPowerLevel.Count; i++)
            {
                var r = f.Credits.ByPowerLevel[i];
                if (r == null) continue;
                Note(bad, $"credits.byPowerLevel row {i} (minPowerLevel {r.MinPowerLevel})",
                     r.Unknown);
            }

            Note(bad, "the stress block", f.Stress.Unknown);
            for (int i = 0; i < f.Stress.ByPowerLevel.Count; i++)
            {
                var r = f.Stress.ByPowerLevel[i];
                if (r == null) continue;
                Note(bad, $"stress.byPowerLevel row {i} (minPowerLevel {r.MinPowerLevel})",
                     r.Unknown);
            }
            return bad;
        }

        // A null bag is a block the file did not contain, which cannot carry a
        // typo; an empty one is a block whose every key was recognised.
        private static void Note(List<string> bad, string where,
                                 Dictionary<string, JsonElement> bag)
        {
            if (bag == null) return;
            foreach (var key in bag.Keys)
                bad.Add($"\"{key}\" is not a recognised key in {where}.");
        }

        // Fail at load, not at the first expiry — four hours into a session,
        // inside a nested postfix, is the worst place to find a config typo.
        private static bool Validate()
        {
            bool ok = true;

            foreach (var t in new[] { ("soloHack", o.Tiers.SoloHack), ("story", o.Tiers.Story),
                                      ("standard", o.Tiers.Standard) })
            {
                if (t.Item2.Multiplier < 0)
                {
                    Plugin.Log.LogError($"Elapse: tiers.{t.Item1}.multiplier is "
                        + $"{t.Item2.Multiplier}; it cannot be negative.");
                    ok = false;
                }
            }
            if (Patterns(o.Tiers.Standard).Length > 0)
                Plugin.Log.LogWarning("Elapse: tiers.standard.patterns is set and means nothing — "
                    + "standard is the tier everything unmatched falls to.");

            var c = o.Credits;
            if (c.Enabled)
            {
                if (c.PercentOfBalance < 0.0 || c.PercentOfBalance > 1.0)
                {
                    Plugin.Log.LogError($"Elapse: credits.percentOfBalance is {c.PercentOfBalance}; "
                        + "it is a fraction and has to be 0.0-1.0.");
                    ok = false;
                }
                ok &= CheckTable("credits", c.ByPowerLevel.Select(r => r.MinPowerLevel).ToList());
                foreach (var r in c.ByPowerLevel)
                    if (r.Amount < 0)
                    {
                        Plugin.Log.LogError($"Elapse: credits.byPowerLevel PL{r.MinPowerLevel} has a "
                            + $"negative amount ({r.Amount}).");
                        ok = false;
                    }
            }

            var s = o.Stress;
            if (s.Enabled)
            {
                if (s.Cap < 1 || s.Cap > 10)
                {
                    Plugin.Log.LogError($"Elapse: stress.cap is {s.Cap}; it has to be 1-10.");
                    ok = false;
                }
                ok &= CheckTable("stress", s.ByPowerLevel.Select(r => r.MinPowerLevel).ToList());
                foreach (var r in s.ByPowerLevel)
                    if (r.MercCount < 0 || r.StressAmount < 0)
                    {
                        Plugin.Log.LogError($"Elapse: stress.byPowerLevel PL{r.MinPowerLevel} has a "
                            + $"negative mercCount or stressAmount ({r.MercCount}/{r.StressAmount}).");
                        ok = false;
                    }
            }

            if (!c.Enabled && !s.Enabled)
            {
                Plugin.Log.LogError("Elapse: both channels are off, so an expiry would resolve to "
                                  + "nothing. Not installing the hook.");
                ok = false;
            }

            if (!ok) Plugin.Log.LogError("Elapse: config rejected; nothing patched.");
            return ok;
        }

        private static bool CheckTable(string where, List<long> mins)
        {
            if (mins.Count == 0)
            {
                Plugin.Log.LogError($"Elapse: {where}.byPowerLevel is empty. Either fill it or set "
                                  + $"{where}.enabled to false.");
                return false;
            }
            if (mins[0] < 1)
            {
                Plugin.Log.LogError($"Elapse: {where}.byPowerLevel starts at minPowerLevel {mins[0]}; "
                    + "the first row has to be 1 or higher. A row at 0 would also catch a mission "
                    + "whose PowerLevelUnscaled could not be read.");
                return false;
            }
            for (int i = 1; i < mins.Count; i++)
            {
                if (mins[i] <= mins[i - 1])
                {
                    Plugin.Log.LogError($"Elapse: {where}.byPowerLevel is not sorted ascending by "
                        + $"minPowerLevel (row {i}: {mins[i]} after {mins[i - 1]}).");
                    return false;
                }
            }
            return true;
        }

        private static string[] Patterns(TierBlock t)
        {
            if (t == null || t.Patterns == null) return new string[0];
            return t.Patterns.Where(p => !string.IsNullOrEmpty(p)).ToArray();
        }

        private static double Mult(TierBlock t) => t == null ? 1.0 : t.Multiplier;

        // ---- patching --------------------------------------------------------

        private static readonly Dictionary<string, Type> TypeCache =
            new Dictionary<string, Type>(StringComparer.Ordinal);

        private static Type ResolveType(string name)
        {
            Type t;
            if (TypeCache.TryGetValue(name, out t)) return t;
            t = AccessTools.TypeByName(name);
            TypeCache[name] = t;
            return t;
        }

        // Two interop proxies resolving to one il2cpp method means two detours
        // on one address. Same check as Fatigue.AlreadyClaimed.
        private static bool AlreadyClaimed(MethodInfo m, IDictionary<IntPtr, string> claimed,
                                           out string owner)
        {
            owner = null;
            IntPtr ptr;
            try
            {
                var field = m.DeclaringType
                    .GetFields(BindingFlags.NonPublic | BindingFlags.Public | BindingFlags.Static)
                    .FirstOrDefault(f => f.FieldType == typeof(IntPtr)
                                      && f.Name.StartsWith("NativeMethodInfoPtr_" + m.Name + "_",
                                                           StringComparison.Ordinal));
                if (field == null) return false;
                ptr = (IntPtr)field.GetValue(null);
            }
            catch { return false; }

            if (ptr == IntPtr.Zero) return false;

            var key = m.DeclaringType?.Name + "." + m.Name;
            string existing;
            if (claimed.TryGetValue(ptr, out existing) && existing != key)
            { owner = existing; return true; }

            claimed[ptr] = key;
            return false;
        }

        private static int Patch(Harmony harmony, string typeName, string methodName,
                                 string postfixName)
        {
            var t = ResolveType(typeName);
            if (t == null)
            {
                Plugin.Log.LogWarning($"Elapse: could not resolve type '{typeName}'.");
                return 0;
            }

            var overloads = AccessTools.GetDeclaredMethods(t)
                .Where(m => m.Name == methodName && !m.IsAbstract).ToList();
            if (overloads.Count == 0)
            {
                Plugin.Log.LogWarning($"Elapse: {t.Name} has no method '{methodName}'.");
                return 0;
            }

            var claimed = new Dictionary<IntPtr, string>();
            var pf = new HarmonyMethod(AccessTools.Method(typeof(Elapse), postfixName));
            int ok = 0;
            foreach (var m in overloads)
            {
                string owner;
                if (AlreadyClaimed(m, claimed, out owner))
                {
                    Plugin.Log.LogWarning($"Elapse: NOT patching {t.Name}.{m.Name} — it is the "
                        + $"same il2cpp method as {owner}.");
                    continue;
                }
                try
                {
                    harmony.Patch(m, postfix: pf);
                    ok++;
                }
                catch (Exception e)
                {
                    Plugin.Log.LogWarning($"Elapse: could not patch {t.Name}.{m.Name}: "
                                        + e.Message);
                }
            }
            return ok;
        }

        // ---- the hook --------------------------------------------------------

        // SaveManager.ProcessTimelineToNextTurn() -> void, instance. No GameDb
        // in the signature; it comes off the SaveManager the hook hands us,
        // read here and dropped: __instance.Dac.GameDBI (Run44-48).
        public static void AfterProcessTimeline(object __instance)
        {
            if (!active || reentrant) return;
            reentrant = true;
            try { Tick(__instance); }
            catch (Exception e)
            {
                // A postfix that throws surfaces inside the game's own turn
                // advance. Losing one tick's expiries is the smaller problem.
                Plugin.Log.LogError($"Elapse: the turn hook threw and was swallowed: {e}");
            }
            finally { reentrant = false; }
        }

        public static void AfterLoadGame()
        {
            if (!active) return;
            try { ForgetSession("a save was loaded"); }
            catch (Exception e)
            {
                Plugin.Log.LogError($"Elapse: the load hook threw and was swallowed: {e}");
            }
        }

        private static void ForgetSession(string why)
        {
            int snaps = previousSnapshot.Count, keys = applied.Count;
            previousSnapshot = new Dictionary<string, Snap>(StringComparer.Ordinal);
            applied.Clear();
            prevTurn = -1;
            maxLogId = -1;
            logBaselined = false;
            // The tick counter goes back to 0 with the rest of the session
            // state. The first-tick instrument line is the proof that the
            // reader can see, and the tick that rebuilds a dropped snapshot is
            // exactly the tick that needs it; without this it was emitted once
            // per process and never again after a load.
            ticks = 0;
            sessionWasReset = true;
            Plugin.Log.LogInfo($"Elapse: {why} — dropped the board snapshot ({snaps} mission(s)) "
                + $"and {keys} double-fire key(s). The next tick rebuilds the snapshot; an "
                + "expiry stamped on that tick cannot be resolved and will be logged as unmatched.");
        }

        private static void Tick(object saveManager)
        {
            object dataLayer;
            object db = Db(saveManager, out dataLayer);
            if (db == null) return;

            var data = Call(db, "ReadGameData", Type.EmptyTypes, new object[0]);
            if (data == null)
            {
                Plugin.Log.LogWarning("Elapse: ReadGameData() returned null on the tick; the turn "
                                    + "is unknown, so nothing is resolved this tick.");
                return;
            }
            long turn;
            if (!TryNum(Get(data, "GameTurn"), out turn))
            {
                Plugin.Log.LogWarning("Elapse: GameDataModel.GameTurn is unreadable on the tick; "
                                    + "nothing is resolved this tick. Worth reporting.");
                return;
            }
            // A reload, another slot, or anything else that moves the turn by
            // other than +1 invalidates everything this session remembers. A
            // turn equal to the previous one is the same tick firing again,
            // which is what the double-fire guard exists for, so it is kept.
            // This is one of two discontinuity signals; the other is on the
            // game log's highest row id, below. Neither catches a reload onto
            // the same or the next turn whose log ids are higher.
            if (prevTurn >= 0 && turn != prevTurn && turn != prevTurn + 1)
                ForgetSession($"the turn moved {prevTurn} -> {turn}");

            // Counted after the check above, because ForgetSession puts it back
            // to 0: this tick is then the first tick of the new session and
            // gets the instrument line.
            ticks++;

            // A. The board, BEFORE the log. Keyed by title; on a duplicate the
            //    nearer EndTurn wins and the loser waits for the next tick.
            bool boardComplete;
            var boardRows = ReadRows(db, "ReadGameMissions", out boardComplete);
            var newSnapshot = new Dictionary<string, Snap>(StringComparer.Ordinal);
            foreach (var m in boardRows)
            {
                var missing = new List<string>();
                var s = new Snap
                {
                    Id = Col(m, "Id", missing),
                    Title = (Str(Get(m, "MissionTitle")) ?? "").Trim(),
                    MissionTypeId = Str(Get(m, "MissionTypeId")),
                    ContactId = Col(m, "ContactId", missing),
                    PowerLevelUnscaled = Col(m, "PowerLevelUnscaled", missing),
                    PowerLevel = Num(Get(m, "PowerLevel")),
                    EndTurn = Col(m, "EndTurn", missing),
                };
                if (string.IsNullOrEmpty(s.Title))
                {
                    NoteUnreadable("GameMissionModel", "MissionTitle");
                    continue;
                }
                if (missing.Count > 0)
                {
                    // Recorded so the expiry is refused with a reason rather
                    // than logged as unmatched, but a row whose EndTurn read
                    // as 0 must not win the title collision below, and its
                    // zeros must not reach the instrument line.
                    s.Unreadable = string.Join(", ", missing);
                    foreach (var c in missing) NoteUnreadable("GameMissionModel", c);
                    if (!newSnapshot.ContainsKey(s.Title)) newSnapshot[s.Title] = s;
                    continue;
                }
                Snap other;
                if (newSnapshot.TryGetValue(s.Title, out other) && other.Unreadable != null)
                    other = null;                       // a readable row always replaces it
                if (other != null)
                {
                    Plugin.Log.LogWarning($"Elapse: turn {turn}: two live missions share the title "
                        + $"'{s.Title}' (ids {other.Id} EndTurn {other.EndTurn}, {s.Id} EndTurn "
                        + $"{s.EndTurn}). Recording only the one with the nearer EndTurn; the "
                        + "other becomes recordable once the first has expired.");
                    if (s.EndTurn >= other.EndTurn) continue;
                }
                newSnapshot[s.Title] = s;
            }

            // The first-tick counters, taken off the snapshot that was actually
            // recorded rather than off the rows as they were read. They used to
            // be incremented inside the loop above, before the title-collision
            // tiebreak could discard the row, so they described rows the
            // snapshot did not hold. Rows with an unreadable column are skipped
            // here: their columns read as 0 and those zeros are not data.
            int withContact = 0, pluRows = 0;
            long pluMin = long.MaxValue, pluMax = long.MinValue;
            foreach (var s in newSnapshot.Values)
            {
                if (s.Unreadable != null) continue;
                if (s.ContactId != 0) withContact++;
                if (s.PowerLevelUnscaled < pluMin) pluMin = s.PowerLevelUnscaled;
                if (s.PowerLevelUnscaled > pluMax) pluMax = s.PowerLevelUnscaled;
                pluRows++;
            }

            // B. This tick's expiries: every 202 row that did not exist on the
            //    previous tick, by Id. Runs 48-55 stamped every such row with
            //    `turn - 1`, but the game moves mission deadlines around on
            //    purpose (a merc's surgery finishing pushes a mission back), so
            //    the stamp is recorded and checked, not relied on. A row that
            //    is new is an expiry whatever turn it carries; a filter on the
            //    stamp would miss a moved one silently, forever. The first
            //    complete read of a session is the baseline and resolves
            //    nothing — the snapshot is empty on that tick anyway.
            bool logsComplete;
            var logRows = ReadRows(db, "ReadGameLogs", out logsComplete);
            if (!logsComplete)
                Plugin.Log.LogWarning($"Elapse: turn {turn}: the game-log read was partial "
                    + $"({logRows.Count} row(s)). The high-water mark is not advanced, so a new "
                    + "expiry row is picked up on the next complete read instead of being lost.");

            var expired = new List<object>();
            int expireRowsTotal = 0;
            long seenMaxId = maxLogId;
            // The highest Id actually present in this read, tracked separately
            // from the watermark (which is seeded from maxLogId and only ever
            // rises, so it cannot report a table whose ids are lower).
            long highestRowId = -1;
            // The lowest row id whose columns could not all be read this tick,
            // and the column that failed. The watermark is not advanced to or
            // past it, so the row is offered again on the next tick instead of
            // being stepped over on the strength of a read that failed.
            long heldAt = long.MaxValue;
            string heldColumn = null;
            bool baseline = !logBaselined;
            foreach (var r in logRows)
            {
                long typeId, rowTurn = 0, rowId;
                if (!TryNum(Get(r, "Id"), out rowId)) { NoteUnreadable("GameLogModel", "Id"); continue; }
                if (rowId > highestRowId) highestRowId = rowId;
                if (!TryNum(Get(r, "LogTypeId"), out typeId))
                {
                    NoteUnreadable("GameLogModel", "LogTypeId");
                    if (rowId < heldAt) { heldAt = rowId; heldColumn = "LogTypeId"; }
                    continue;
                }
                if (typeId == LogTypeMissionExpire)
                {
                    expireRowsTotal++;
                    if (!TryNum(Get(r, "GameTurn"), out rowTurn))
                    {
                        NoteUnreadable("GameLogModel", "GameTurn");
                        if (rowId < heldAt) { heldAt = rowId; heldColumn = "GameTurn"; }
                        continue;
                    }
                }

                // Only a row that was fully classified may be stepped over. The
                // watermark used to be raised on the row's Id before either
                // column was read, so a row that failed one of them was above
                // the mark on the next tick and was never looked at again.
                if (rowId > seenMaxId) seenMaxId = rowId;
                if (typeId != LogTypeMissionExpire) continue;

                if (baseline)
                {
                    // Nothing resolves on the baseline tick, but a row stamped
                    // with the turn that just ended is one this session was
                    // not there to see. Say so rather than fold it in.
                    if (rowTurn == turn - 1)
                        Plugin.Log.LogWarning($"Elapse: turn {turn}: log row {rowId} "
                            + $"'{Str(Get(r, "LogTitle"))}' (LogTypeId 202, GameTurn {rowTurn}) was "
                            + "already present on this session's first tick, so there is no board "
                            + "snapshot to resolve it against. No penalty. Expected right after a "
                            + "load; otherwise worth reporting.");
                    continue;
                }
                if (rowId <= maxLogId) continue;

                expired.Add(r);
                if (rowTurn != turn - 1)
                    Plugin.Log.LogWarning($"Elapse: turn {turn}: new log row {rowId} "
                        + $"'{Str(Get(r, "LogTitle"))}' is stamped GameTurn {rowTurn} (delta "
                        + $"{rowTurn - turn}), not {turn - 1}. Resolving it by row id regardless; "
                        + "the stamp is recorded so the game's deadline shifts can be measured.");
            }

            // The second discontinuity signal. maxLogId only rises within a
            // session, so loading a different save whose current turn happens to
            // land on prevTurn or prevTurn + 1 slips past the turn check above;
            // if that save's log ids are lower, the mark sits above every row it
            // has and no expiry is ever seen again. The highest id in a COMPLETE
            // read is a property of the save: below the mark, this is not the
            // log table that was baselined. Only a complete read is acted on — a
            // partial one can legitimately miss the top rows. Nothing resolved
            // above can be lost by this: `expired` only ever takes rows above
            // maxLogId, and every row here is at or below highestRowId.
            if (logsComplete && logBaselined && highestRowId >= 0 && highestRowId < maxLogId)
            {
                ForgetSession($"the game log's highest row id is {highestRowId}, below this "
                    + $"session's high-water mark {maxLogId}, so this is not the log table that "
                    + "was baselined");
                // Re-baseline off the table actually in front of us; seenMaxId
                // was seeded from the mark that has just been dropped.
                seenMaxId = highestRowId;
            }

            // Hold the mark below any row this tick could not classify, and say
            // so, so the retry is visible instead of silent. Never below the
            // mark already reached: a row at or under it was stepped over on an
            // earlier tick and holding there would re-offer rows already
            // resolved.
            //
            // Holding does re-offer every row ABOVE the held one, including 202
            // rows that resolved on this tick. What stops those being charged
            // twice is section C's other precondition: a resolved title is
            // removed from the snapshot and the mission row itself is gone from
            // the board, so on the next tick they find no match and are logged
            // as unmatched rather than charged. Re-offering is the deliberate
            // cost of not stepping over a row the reader could not classify.
            if (heldColumn != null && heldAt > maxLogId && seenMaxId >= heldAt)
            {
                Plugin.Log.LogWarning($"Elapse: turn {turn}: game-log row {heldAt} could not be "
                    + $"classified because its {heldColumn} was unreadable. Holding the high-water "
                    + $"mark at {heldAt - 1} instead of {seenMaxId}, so that row and everything "
                    + "above it are read again on the next tick rather than being stepped over.");
                seenMaxId = heldAt - 1;
            }

            if (logsComplete)
            {
                maxLogId = seenMaxId;
                logBaselined = true;
            }

            // The instrument's own proof that it can see. AGENTS.md §3: a quiet
            // session has to be distinguishable from a reader that returns
            // nothing. The reference save carries 20 x 202 rows at turn 1382.
            // It fires again after a session reset because ForgetSession puts
            // `ticks` back to 0, so the wording says which of the two this is.
            // pluMin/pluMax only mean anything when a readable row set them:
            // an unreadable row is still recorded in the snapshot, so counting
            // the snapshot instead used to print the long sentinels.
            if (ticks == 1)
            {
                string when = sessionWasReset ? "first tick after a session reset"
                                              : "first tick of the process";
                Plugin.Log.LogInfo($"Elapse: {when} at turn {turn}: {logRows.Count} game-log "
                    + $"row(s){(logsComplete ? "" : " (partial)")}, {expireRowsTotal} of them "
                    + $"LogTypeId 202; board {boardRows.Count} mission(s)"
                    + $"{(boardComplete ? "" : " (partial)")}, {withContact} with a contact, "
                    + (pluRows > 0 ? $"PowerLevelUnscaled {pluMin}-{pluMax}"
                       : newSnapshot.Count > 0 ? "no readable PowerLevelUnscaled" : "no snapshot")
                    + $"; highest log row id {seenMaxId}. Rows above it on later ticks are new.");
            }

            // C. Resolve each against the PREVIOUS snapshot.
            foreach (var r in expired)
            {
                string logTitle = Str(Get(r, "LogTitle"));
                string stamp = $"log row {Num(Get(r, "Id"))} stamped {Num(Get(r, "GameTurn"))}";
                string title = logTitle;
                if (title.EndsWith(WindowClosedSuffix, StringComparison.Ordinal))
                    title = title.Substring(0, title.Length - WindowClosedSuffix.Length);
                title = title.Trim();

                string key = turn + ":" + title;
                if (applied.Contains(key))
                {
                    Plugin.Log.LogWarning($"Elapse: turn {turn}: '{title}' was already resolved at "
                        + "this turn — the same tick firing again, a reload to this exact turn, or "
                        + "a second mission with this title expiring on the same turn. Not charging "
                        + "again.");
                    continue;
                }

                Snap snap;
                if (!previousSnapshot.TryGetValue(title, out snap))
                {
                    Plugin.Log.LogWarning($"Elapse: turn {turn}: {stamp} "
                        + $"'{logTitle}' (LogTypeId 202) has no match in the "
                        + $"previous board snapshot ({previousSnapshot.Count} mission(s) as of turn "
                        + $"{prevTurn}). No penalty. Expected on the first tick after a load; "
                        + "otherwise worth reporting.");
                    continue;
                }

                applied.Add(key);
                previousSnapshot.Remove(title);     // releases the title (§3.1)
                expiriesSeen++;

                if (snap.Unreadable != null)
                {
                    Plugin.Log.LogWarning($"Elapse: turn {turn} '{title}' (mission {snap.Id}): "
                        + $"{snap.Unreadable} could not be read when the board was snapshotted. "
                        + "Refusing to charge on a value read as 0. Worth reporting.");
                    continue;
                }
                if (snap.ContactId == 0)
                {
                    Plugin.Log.LogInfo($"Elapse: turn {turn} '{title}' ({snap.MissionTypeId}) "
                        + "has no contact (ContactId 0) — skipped, no penalty.");
                    continue;
                }

                try { Resolve(saveManager, db, dataLayer, turn, snap, stamp); }
                catch (Exception e)
                {
                    Plugin.Log.LogError($"Elapse: resolving '{title}' threw and was swallowed: {e}");
                }
            }

            // Only ever replace the snapshot from a read that finished. A
            // partial read would report every missing mission as expired-and-
            // gone, and the snapshot is the only copy of those columns.
            // ...and only when the log read finished too: a 202 row that a
            // partial log read hid is picked up on the next complete read, and
            // it can only be resolved if the snapshot that still holds its
            // mission has not been replaced in the meantime.
            if (boardComplete && logsComplete) previousSnapshot = newSnapshot;
            else if (!boardComplete)
                Plugin.Log.LogWarning($"Elapse: turn {turn}: the mission board read was partial or "
                    + $"failed ({boardRows.Count} row(s)). Keeping the previous snapshot.");
            else
                Plugin.Log.LogWarning($"Elapse: turn {turn}: keeping the previous board snapshot "
                    + "because the game-log read was partial; the next complete read resolves "
                    + "against it.");
            prevTurn = turn;
        }

        // ---- resolution ------------------------------------------------------

        // What one channel did with one expiry, reported alongside the summary
        // string so the caller does not have to match on prose.
        //
        //   Applied         something was written.
        //   NothingToApply  there was nothing to write: the table row is off at
        //                   this power level, the amount is 0, the balance is
        //                   empty, nobody was eligible. A legitimate zero-target
        //                   outcome, not an instrument failure.
        //   Failed          the channel could not do what it was asked to do.
        //   Unknown         a write was made and its outcome could not be read.
        private enum ChannelResult { Applied, NothingToApply, Failed, Unknown }

        // Sorts one channel's result into the two lists the half-application
        // report is built from. A channel that was disabled (null) or had
        // nothing to apply to belongs in neither.
        private static void NoteChannel(string name, ChannelResult? r, List<string> landed,
                                        List<string> missed)
        {
            if (!r.HasValue) return;
            if (r.Value == ChannelResult.Applied) landed.Add(name);
            else if (r.Value == ChannelResult.Failed) missed.Add(name + " could not be applied");
            else if (r.Value == ChannelResult.Unknown)
                missed.Add(name + " was attempted and its outcome could not be read");
        }

        private static void Resolve(object saveManager, object db, object dataLayer, long turn,
                                    Snap snap, string stamp)
        {
            string tierName;
            double mult = Classify(snap.MissionTypeId, out tierName);
            long pl = snap.PowerLevelUnscaled;
            bool verbose = expiriesSeen <= logFirst;

            var head = $"Elapse: turn {turn} '{snap.Title}' (mission {snap.Id}, "
                     + $"{snap.MissionTypeId}, EndTurn {snap.EndTurn}, {stamp}) contact {snap.ContactId} "
                     + $"tier={tierName} x{mult:0.##} PL {pl} (scaled {snap.PowerLevel})";
            var summary = new List<string>();

            // The head goes out BEFORE any write, so a native fault inside a
            // write still leaves a record of what was being attempted.
            Plugin.Log.LogInfo(head);

            // Null while a channel is disabled; set to what the channel did
            // otherwise. Compared at the bottom of this method.
            ChannelResult? creditsResult = null, stressResult = null;

            // Channel 1 — credits.
            if (o.Credits.Enabled)
            {
                var row = CreditsRowFor(pl);
                long balance;
                bool haveBalance = ReadBalance(saveManager, db, out balance);
                long amount = 0;
                if (row != null && row.Amount > 0)
                    amount += (long)Math.Round(row.Amount * mult, MidpointRounding.AwayFromZero);
                if (o.Credits.PercentOfBalance > 0 && haveBalance)
                    amount += (long)Math.Round(balance * o.Credits.PercentOfBalance,
                                               MidpointRounding.AwayFromZero);

                // David's ruling, 2026-08-31: a fine the crew cannot cover takes
                // what they have. When the balance is readable the charge is
                // capped to it here, so SpendCredits is asked for an amount it
                // can grant and its refusal is a backstop, not the floor. When
                // the balance is NOT readable that premise is gone: the full
                // amount goes in, because the engine owns the balance and
                // declining to charge would be a silent failure of its own. The
                // dropped premise is reported once rather than left implied.
                long charge = haveBalance ? Math.Min(amount, Math.Max(0, balance)) : amount;
                if (!haveBalance && charge > 0 && !warnedUncappedCharge)
                {
                    warnedUncappedCharge = true;
                    Plugin.Log.LogWarning("Elapse: the credit balance could not be read, so the "
                        + $"charge ({charge}) could not be capped to it. SpendCredits is being "
                        + "asked for an amount that may be more than the crew has, and whatever "
                        + "the engine does with that is what happens. Reported once, worth "
                        + "reporting.");
                }
                string capped = haveBalance && charge < amount
                              ? $" (fine {amount}, capped to the balance)" : "";

                if (row == null)
                {
                    summary.Add($"credits: PL {pl} is below the first table row, channel off");
                    creditsResult = ChannelResult.NothingToApply;
                }
                else if (amount <= 0)
                {
                    summary.Add("credits: 0, nothing charged");
                    creditsResult = ChannelResult.NothingToApply;
                }
                else if (charge <= 0)
                {
                    summary.Add($"credits {amount}: balance is {balance}, nothing to take");
                    creditsResult = ChannelResult.NothingToApply;
                }
                else
                {
                    ChannelResult spent;
                    summary.Add(SpendCredits(saveManager, db, snap, charge, haveBalance, balance,
                                             out spent) + capped);
                    creditsResult = spent;
                }
            }

            // Channel 2 — stress.
            if (o.Stress.Enabled)
            {
                var row = StressRowFor(pl);
                if (row == null)
                {
                    summary.Add($"stress: PL {pl} is below the first table row, channel off");
                    stressResult = ChannelResult.NothingToApply;
                }
                else
                {
                    long count = row.MercCount;
                    if (o.Stress.ApplyTierMultiplier)
                        count = (long)Math.Round(count * mult, MidpointRounding.AwayFromZero);
                    if (count <= 0 || row.StressAmount <= 0)
                    {
                        summary.Add($"stress: {count} merc(s) +{row.StressAmount}, nothing to do");
                        stressResult = ChannelResult.NothingToApply;
                    }
                    else
                    {
                        ChannelResult stressed;
                        summary.Add(ApplyStress(saveManager, db, dataLayer, turn, snap, count,
                                                row.StressAmount, out stressed));
                        stressResult = stressed;
                    }
                }
            }

            // A half-applied expiry. The double-fire key was taken and the
            // snapshot entry released before either channel ran, and neither is
            // rolled back — charging twice is worse than a half application —
            // so the one thing owed here is a plain statement of what landed,
            // what did not, and that nothing will come back for it.
            var landed = new List<string>();
            var missed = new List<string>();
            NoteChannel("credits", creditsResult, landed, missed);
            NoteChannel("stress", stressResult, landed, missed);
            if (landed.Count > 0 && missed.Count > 0)
                Plugin.Log.LogError($"Elapse: turn {turn} '{snap.Title}' (mission {snap.Id}) was "
                    + $"applied in PART: {string.Join(" and ", landed)} went through; "
                    + $"{string.Join(" and ", missed)}. The expiry is already marked resolved — the "
                    + "double-fire key was taken and the board snapshot entry released before "
                    + "either channel ran — and nothing rolls back or retries it, so this mission "
                    + "stays half-penalised for the rest of the session. Worth reporting.");

            if (verbose)
                foreach (var line in summary) Plugin.Log.LogInfo("Elapse:   " + line);
            else
                Plugin.Log.LogInfo("Elapse:   " + string.Join("; ", summary));
        }

        // First match wins: soloHack, then story, then standard. Substring on
        // MissionTypeId, the same idiom [MissionRewards] uses.
        private static double Classify(string missionTypeId, out string tierName)
        {
            var id = missionTypeId ?? "";
            foreach (var p in Patterns(o.Tiers.SoloHack))
                if (id.IndexOf(p, StringComparison.Ordinal) >= 0)
                { tierName = "soloHack"; return Mult(o.Tiers.SoloHack); }
            foreach (var p in Patterns(o.Tiers.Story))
                if (id.IndexOf(p, StringComparison.Ordinal) >= 0)
                { tierName = "story"; return Mult(o.Tiers.Story); }
            tierName = "standard";
            return Mult(o.Tiers.Standard);
        }

        // Last row whose minPowerLevel is at or below the level; null when the
        // level is below the first row.
        private static CreditsRow CreditsRowFor(long pl)
        {
            CreditsRow hit = null;
            foreach (var r in o.Credits.ByPowerLevel) if (r.MinPowerLevel <= pl) hit = r;
            return hit;
        }

        private static StressRow StressRowFor(long pl)
        {
            StressRow hit = null;
            foreach (var r in o.Stress.ByPowerLevel) if (r.MinPowerLevel <= pl) hit = r;
            return hit;
        }

        // ---- channel 1: credits ----------------------------------------------

        // The engine's live GameDataModel (SaveManager.GameData) is the
        // authority — Run52 saw it move first and the row follow a tick later.
        // The row is the fallback for the log line only.
        private static bool ReadBalance(object saveManager, object db, out long balance)
        {
            balance = 0;
            var live = Get(saveManager, "GameData");
            var v = live == null ? null : Get(live, "Credits");
            if (v == null)
            {
                if (!warnedNoLiveCredits)
                {
                    warnedNoLiveCredits = true;
                    Plugin.Log.LogWarning("Elapse: SaveManager.GameData.Credits is unreadable; "
                        + "logging the balance off the database row instead. The spend itself "
                        + "still goes through SpendCredits.");
                }
                var row = Call(db, "ReadGameData", Type.EmptyTypes, new object[0]);
                v = row == null ? null : Get(row, "Credits");
                if (v == null) return false;
            }
            try { balance = Convert.ToInt64(v, CultureInfo.InvariantCulture); return true; }
            catch { return false; }
        }

        private static string SpendCredits(object saveManager, object db, Snap snap, long amount,
                                           bool haveBalance, long before, out ChannelResult result)
        {
            string reason = $"CKF Hard Mode: {snap.Title} window closed";
            object ret;
            try
            {
                ret = Call(saveManager, "SpendCredits", new[] { typeof(long), typeof(string) },
                           new object[] { amount, reason });
            }
            catch (Exception e)
            {
                var inner = e.InnerException ?? e;
                Plugin.Log.LogError($"Elapse: SpendCredits({amount}) THREW {inner.GetType().Name}: "
                                  + $"{inner.Message}. Nothing charged for '{snap.Title}'.");
                result = ChannelResult.Failed;
                return $"credits {amount}: SpendCredits threw, nothing charged";
            }

            long after;
            bool haveAfter = ReadBalance(saveManager, db, out after);
            string bal = haveBalance ? before.ToString() : "?";
            string balAfter = haveAfter ? after.ToString() : "?";
            string retText = ret == null
                           ? "null (a void return, or an overload that returns nothing)"
                           : $"{Str(ret)} ({ret.GetType().Name})";

            // Call resolves an overload by parameter types only, so on a build
            // whose SpendCredits(long, string) is void — or returns anything
            // that is not a bool — `ret` is not a refusal and must not be read
            // as one. It used to be: anything but a true bool was reported as
            // "nothing charged" while the balance may well have moved. Three
            // outcomes, distinguished by the balance read-back already in hand.
            if (!(ret is bool))
            {
                if (haveBalance && haveAfter && after == before - amount)
                {
                    if (!warnedSpendNotBool)
                    {
                        warnedSpendNotBool = true;
                        Plugin.Log.LogWarning("Elapse: SpendCredits(long, string) does not return "
                            + $"a bool on this build — it returned {retText}. Acceptance is being "
                            + "inferred from the live balance moving by the charged amount instead "
                            + "of from the return value. Reported once, worth reporting.");
                    }
                    Plugin.Log.LogWarning($"Elapse: WROTE credits: SpendCredits({amount}, "
                        + $"\"{reason}\") returned {retText}; live balance {bal} -> {balAfter}, "
                        + "which is exactly the charge, so the spend is taken to have been "
                        + "accepted.");
                    result = ChannelResult.Applied;
                    return $"credits {amount} -> balance {bal} -> {balAfter} (accepted by the "
                         + "balance; SpendCredits returned no bool)";
                }

                Plugin.Log.LogError($"Elapse: SpendCredits({amount}, \"{reason}\") did not throw "
                    + $"and did not return a bool — it returned {retText}. The live balance read "
                    + $"{bal} before the call and {balAfter} after"
                    + (haveBalance && haveAfter ? $", not the {before - amount} a completed charge "
                                                + "would leave" : "")
                    + ". Whether the spend took CANNOT be determined from here: it is not being "
                    + "called a refusal and it is not being called a charge. Worth reporting.");
                result = ChannelResult.Unknown;
                return $"credits {amount}: UNKNOWN whether it was charged (no bool returned), "
                     + $"balance {bal} -> {balAfter}";
            }

            if (!(bool)ret)
            {
                // The charge was capped to the live balance when that balance
                // could be read, so a refusal here means the engine and the
                // live object disagree about what the crew has. Nothing is
                // charged either way.
                Plugin.Log.LogWarning($"Elapse: SpendCredits({amount}, \"{reason}\") returned "
                    + $"{Str(ret)} — the engine refused a spend the live balance ({bal}) said it "
                    + "could cover. Nothing charged. Worth reporting.");
                result = ChannelResult.Failed;
                return $"credits {amount}: REFUSED by SpendCredits, balance {bal} unchanged";
            }
            Plugin.Log.LogWarning($"Elapse: WROTE credits: SpendCredits({amount}, \"{reason}\") "
                + $"returned true; live balance {bal} -> {balAfter}.");
            if (haveBalance && haveAfter && after != before - amount)
                Plugin.Log.LogWarning($"Elapse: SpendCredits({amount}) returned true but the live "
                    + $"balance reads {after}, not {before - amount}. Worth reporting.");
            result = ChannelResult.Applied;
            return $"credits {amount} -> balance {bal} -> {balAfter}";
        }

        // ---- channel 2: stress -----------------------------------------------

        private sealed class Merc
        {
            public object Row;
            public long Id, Status;
            public string Name;
            public int Sign;                // +1 positive, -1 negative, 0 neutral
            public string Verb = "";        // the edge that decided it, for the log
            public long Score;              // TagScore of that edge — logged, unused
            public ulong Order;
            public object Cached;           // SaveManager.playerCache[Id].CharacterModel, if any
        }

        private static string ApplyStress(object saveManager, object db, object dataLayer,
                                          long turn, Snap snap, long count, long amount,
                                          out ChannelResult result)
        {
            bool rosterComplete;
            var roster = ReadRows(db, "ReadGameCharacters", out rosterComplete);
            if (roster.Count == 0)
            {
                Plugin.Log.LogWarning($"Elapse: turn {turn}: ReadGameCharacters() returned nothing "
                    + $"({(rosterComplete ? "complete" : "partial")}); no stress applied for "
                    + $"'{snap.Title}'.");
                result = ChannelResult.Failed;
                return "stress: roster unreadable, nothing applied";
            }
            if (!rosterComplete)
                Plugin.Log.LogWarning($"Elapse: turn {turn}: the roster read was partial "
                                    + $"({roster.Count} row(s)); the pool is short this expiry.");

            bool tagsComplete;
            var tags = ReadRows(db, "ReadGameCharacterTags", out tagsComplete);
            if (!tagsComplete)
                Plugin.Log.LogWarning($"Elapse: turn {turn}: the character-tag read was partial "
                    + $"({tags.Count} row(s)); some merc-contact edges may be missed this expiry.");

            var relTypes = RelTypes(dataLayer, tags);
            if (relTypes == null)
            {
                result = ChannelResult.Failed;
                return "stress: TagModel.RelType unreadable (DataDb.ReadTags and TagData both "
                     + "empty), so mercs cannot be partitioned; nothing applied";
            }

            // Partition the roster by its own edges toward the contact.
            string actor = ContactActorPrefix + snap.ContactId;
            var mercs = new List<Merc>();
            var excluded = new List<string>();
            foreach (var row in roster)
            {
                long id;
                if (!TryNum(Get(row, "Id"), out id))
                {
                    NoteUnreadable("GameCharacterModel", "Id");
                    continue;           // an Id of 0 would match every tag and be written to
                }
                if (o.Stress.SafehouseOnly)
                {
                    string howC;
                    var live = CachedCharacterModel(saveManager, id, out howC);
                    bool? inSafehouse = SafehouseAliveAndActive(live ?? row);
                    if (inSafehouse == false)
                    {
                        excluded.Add($"{id} {Str(Get(row, "DisplayName"))} (Status {Num(Get(row, "Status"))})");
                        continue;
                    }
                }
                var m = new Merc
                {
                    Row = row,
                    Id = id,
                    Name = Str(Get(row, "DisplayName")),
                    Status = Num(Get(row, "Status")),
                };
                string posVerb = null, negVerb = null;
                long posScore = 0, negScore = 0;
                foreach (var t in tags)
                {
                    long owner;
                    if (!TryNum(Get(t, "CharacterId"), out owner)) { NoteUnreadable("GameCharacterTagModel", "CharacterId"); continue; }
                    if (owner != m.Id) continue;
                    var actorId = Get(t, "ActorId");
                    if (actorId == null) { NoteUnreadable("GameCharacterTagModel", "ActorId"); continue; }
                    if (!string.Equals(Str(actorId), actor, StringComparison.Ordinal)) continue;
                    string verb = Str(Get(t, "TagTypeId"));
                    if (string.IsNullOrEmpty(verb)) { NoteUnreadable("GameCharacterTagModel", "TagTypeId"); continue; }
                    long rel;
                    if (!relTypes.TryGetValue(verb, out rel))
                    {
                        Plugin.Log.LogWarning($"Elapse: tag '{verb}' on merc {m.Id} has no TagModel "
                                            + "row; treated as neutral.");
                        rel = 0;
                    }
                    if (rel > 0 && posVerb == null) { posVerb = verb; posScore = Num(Get(t, "TagScore")); }
                    if (rel < 0 && negVerb == null) { negVerb = verb; negScore = Num(Get(t, "TagScore")); }
                }
                // Exclusion wins: a merc with both a +1 and a -1 edge is negative.
                if (negVerb != null)      { m.Sign = -1; m.Verb = negVerb; m.Score = negScore; }
                else if (posVerb != null) { m.Sign = 1;  m.Verb = posVerb; m.Score = posScore; }
                mercs.Add(m);
            }

            // Seeded order. Same turn, same mission, same victims on every reload.
            ulong seed = Mix((ulong)turn, snap.Id > 0 ? (ulong)snap.Id : Fnv1a(snap.Title))
                       ^ (ulong)o.SeedSalt;
            foreach (var m in mercs) m.Order = Mix(seed, (ulong)m.Id);

            string excludedNow = string.Join(", ", excluded);
            if (excluded.Count > 0 && excludedNow != lastExcluded)
                Plugin.Log.LogInfo($"Elapse:   not in the safehouse (IsStatusSafehouseAliveAndActive "
                    + $"false), excluded: {excludedNow}");
            lastExcluded = excludedNow;

            var positive = mercs.Where(m => m.Sign > 0).OrderBy(m => m.Order).ThenBy(m => m.Id).ToList();
            var neutral  = mercs.Where(m => m.Sign == 0).OrderBy(m => m.Order).ThenBy(m => m.Id).ToList();
            int negatives = mercs.Count(m => m.Sign < 0);

            var pick = new List<Merc>();
            foreach (var m in positive) { if (pick.Count >= count) break; pick.Add(m); }
            if (pick.Count < count && o.Stress.FallbackToRandom)
                foreach (var m in neutral) { if (pick.Count >= count) break; pick.Add(m); }

            if (pick.Count < count)
                Plugin.Log.LogWarning($"Elapse: turn {turn} '{snap.Title}': wanted {count} merc(s), "
                    + $"found {pick.Count} ({positive.Count} positive, {neutral.Count} neutral, "
                    + $"{negatives} negative toward contact {snap.ContactId}"
                    + (o.Stress.FallbackToRandom ? "" : "; fallbackToRandom is off") + ").");
            if (pick.Count == 0)
            {
                // Not a failure of the instrument: the roster and the tags were
                // read, and the answer is that this contact has nobody who
                // qualifies. Zero targets, not "could not apply".
                result = ChannelResult.NothingToApply;
                return $"stress +{amount} x{count}: nobody eligible ({positive.Count} positive, "
                     + $"{neutral.Count} neutral, {negatives} negative)";
            }

            // How the picks went, for the caller's success signal. A merc
            // already at the cap counts as neither: nothing was owed there.
            int wroteCount = 0, refusedCount = 0;
            var parts = new List<string>();
            foreach (var m in pick)
            {
                // ONE AUTHORITY, AND IT IS THE CACHE.
                //
                // SaveManager.playerCache holds a live PlayerModel per merc
                // whose CharacterModel is what the roster panel reads and what
                // the engine's own stress code takes (Run55, from the interop
                // metadata). The GameDb row is a write-through copy: durable
                // (Runs 49-51) but not what anything reads back. So `before`
                // comes from the cached object and from nothing else, and the
                // row is only consulted when there is no cached object to ask.
                //
                // This replaces a rule that read BOTH and took the higher of
                // the two. That rule was written to stop the cache-derived
                // value being written down onto a row that read higher — a
                // case that has never been observed. Log18 carries 42 watch
                // samples over 7 writes and 6 mercs, every one of them
                // `row N, cache N`, no disagreement warning, and no merc
                // without a cache entry in any run. Reading two objects to
                // arbitrate between them was carrying a contradiction the data
                // does not show, so it is gone. [measured: Logs/Log18.txt]
                //
                // What that gives up: nothing now compares the two, so a
                // divergence would go unseen here. The read-back in
                // WriteStress still re-reads the row through a fresh
                // ReadGameCharacters() and warns when it does not hold the
                // value that was written, so the row is not entirely
                // uninstrumented — but it is checked against what we wrote,
                // not against the cache.
                string how;
                m.Cached = CachedCharacterModel(saveManager, m.Id, out how);

                long before = 0;
                bool haveBefore = false;
                if (m.Cached != null)
                {
                    if (TryNum(Get(m.Cached, "NegativeTraitValue"), out before))
                    {
                        haveBefore = true;
                    }
                    else
                    {
                        // The authority is present but unreadable. Fall back to
                        // the row rather than write a number computed from
                        // nothing, and drop the cache for this merc so the
                        // write below takes the row path too.
                        Plugin.Log.LogWarning($"Elapse: merc {m.Id} {m.Name}: the cached "
                            + "PlayerModel's NegativeTraitValue is unreadable; falling back to "
                            + "the row for this merc.");
                        m.Cached = null;
                        how = "cached value unreadable";
                    }
                }

                if (!haveBefore && !TryNum(Get(m.Row, "NegativeTraitValue"), out before))
                {
                    Plugin.Log.LogError($"Elapse: NegativeTraitValue is unreadable on merc {m.Id} "
                        + $"{m.Name} on both the cached PlayerModel and the row; refusing to write "
                        + "a value computed from nothing.");
                    parts.Add($"{m.Id} {m.Name}: column unreadable, skipped");
                    refusedCount++;
                    continue;
                }
                if (m.Cached == null && how.StartsWith("cached CharacterModel has Id", StringComparison.Ordinal))
                {
                    if (!warnedCacheMiskeyed)
                    {
                        warnedCacheMiskeyed = true;
                        Plugin.Log.LogError($"Elapse: playerCache[{m.Id}] holds a CharacterModel for a "
                            + $"different merc ({how}). The cache is not keyed by CharacterId as "
                            + "assumed; every write takes the row path. Reported once, worth reporting.");
                    }
                }
                else if (m.Cached == null && !warnedNoCache)
                {
                    warnedNoCache = true;
                    Plugin.Log.LogWarning($"Elapse: no cached PlayerModel for merc {m.Id} {m.Name} "
                        + $"({how}); writing the row only. The roster panel may not show the change "
                        + "until the engine re-reads. Reported once.");
                }
                string who = $"{m.Id} {m.Name} ({(m.Sign > 0 ? m.Verb : m.Sign == 0 ? "neutral" : m.Verb)}"
                           + (m.Sign != 0 ? $", score {m.Score}, {(m.Sign > 0 ? "+1" : "-1")}" : "")
                           + $", Status {m.Status})";

                // The cap bounds the INCREASE. A merc already at or above it
                // is left exactly where they are — this must never lower
                // Stress. `before` is the authority's value, so the test is
                // against the number the game itself is showing.
                if (before >= o.Stress.Cap)
                {
                    parts.Add($"{who} {before} at or above cap {o.Stress.Cap}, unchanged");
                    continue;
                }
                long after = Math.Min(o.Stress.Cap, before + amount);
                bool wrote;
                parts.Add(WriteStress(saveManager, db, turn, m, before, after, who, out wrote));
                if (wrote) wroteCount++; else refusedCount++;
            }

            // Applied when at least one merc took the value. Every pick failing
            // is a failure; every pick sitting at the cap is a legitimate
            // nothing-to-do.
            result = wroteCount > 0 ? ChannelResult.Applied
                   : refusedCount > 0 ? ChannelResult.Failed
                   : ChannelResult.NothingToApply;
            return $"stress +{amount} x{count} -> [{string.Join("; ", parts)}]";
        }

        private static string WriteStress(object saveManager, object db, long turn, Merc m,
                                          long before, long after, string who, out bool wrote)
        {
            // Both objects get the value; the cached one, when it exists, is
            // the one handed to UpdateGameCharacter, because it carries the
            // engine's latest in-memory state for the other 100-odd columns
            // and is what the engine would write back anyway. Which of them
            // actually took the value is tracked, because the revert below has
            // to put back exactly those and no others.
            object target = m.Cached ?? m.Row;
            if (!Set(target, "NegativeTraitValue", after))
            {
                wrote = false;
                return $"{who} {before}: could not set NegativeTraitValue, unchanged";
            }
            bool rowWritten = m.Cached == null;         // then `target` was the row itself
            if (m.Cached != null)
            {
                rowWritten = Set(m.Row, "NegativeTraitValue", after);
                if (!rowWritten)
                    Plugin.Log.LogWarning($"Elapse: merc {m.Id}: set NegativeTraitValue on the "
                        + "cached PlayerModel but not on the row object. Continuing.");
            }

            object ret;
            try { ret = Call1(db, "UpdateGameCharacter", target); }
            catch (Exception e)
            {
                var inner = e.InnerException ?? e;
                // Put back every object this method actually wrote — the cached
                // PlayerModel when there is one, and the row object when it took
                // the value — so nothing is left holding a number the database
                // does not have. Each revert is reported on its own result.
                // Correcting what stood here: the old revert short-circuited to
                // "reverted" whenever there was no cache, having put nothing
                // back although the row had been written through `target`, and
                // when there was a cache it restored only the cache and left
                // the row at `after`.
                var back = new List<string>();
                var stuck = new List<string>();
                if (m.Cached != null)
                    (Set(m.Cached, "NegativeTraitValue", before) ? back : stuck)
                        .Add("the cached PlayerModel");
                if (rowWritten)
                    (Set(m.Row, "NegativeTraitValue", before) ? back : stuck)
                        .Add("the row object");
                Plugin.Log.LogError($"Elapse: UpdateGameCharacter THREW {inner.GetType().Name}: "
                    + $"{inner.Message} — merc {m.Id} {m.Name}, NegativeTraitValue "
                    + $"{before} -> {after} not persisted"
                    + (back.Count > 0
                       ? $"; {string.Join(" and ", back)} put back to {before}" : "")
                    + (stuck.Count > 0
                       ? $"; {string.Join(" and ", stuck)} COULD NOT be put back and still reads "
                       + after : "")
                    + ".");
                wrote = false;
                return $"{who} {before}: UpdateGameCharacter threw";
            }

            // Read back through a FRESH reader, not the object we mutated. The
            // reader's own completeness flag is inspected: a read-back that
            // could not be performed is not evidence about the write, and
            // reporting it as one blamed writes that had taken.
            long readBack = long.MinValue;
            bool complete;
            foreach (var row in ReadRows(db, "ReadGameCharacters", out complete))
                if (Num(Get(row, "Id")) == m.Id) { readBack = Num(Get(row, "NegativeTraitValue")); break; }

            bool checkable = readBack != long.MinValue || complete;
            string rb = readBack != long.MinValue ? readBack.ToString()
                      : complete ? "no row" : "not read back";
            if (!checkable)
                Plugin.Log.LogWarning($"Elapse: NegativeTraitValue on merc {m.Id} {m.Name}: wrote "
                    + $"{after}, UpdateGameCharacter returned {Str(ret)}, and the read-back could "
                    + "not be performed — the roster re-read was partial and never reached this "
                    + "merc's row. Nothing is known either way about whether the write took.");
            else if (readBack != after)
                Plugin.Log.LogWarning($"Elapse: NegativeTraitValue on merc {m.Id} {m.Name}: wrote "
                    + $"{after}, UpdateGameCharacter returned {Str(ret)}, a fresh read gives {rb}. "
                    + "The write may not have taken.");
            Plugin.Log.LogWarning($"Elapse: WROTE stress: merc {m.Id} {m.Name} NegativeTraitValue "
                + $"{before} -> {after} via {(m.Cached != null ? "cached PlayerModel" : "row")}, "
                + $"UpdateGameCharacter returned {Str(ret)}, row reads {rb}.");

            wrote = true;
            return $"{who} {before} -> {after}"
                 + (m.Cached != null ? "" : " (row only)")
                 + (readBack == after ? "" : $" (read back {rb})");
        }

        // SaveManager.playerCache : Dictionary<long, PlayerModel>, and
        // PlayerModel.CharacterModel is the GameCharacterModel the roster
        // panel and the engine's own stress code work on. Null when the merc
        // is not cached, with `how` saying why.
        private static object CachedCharacterModel(object saveManager, long id, out string how)
        {
            how = "";
            try
            {
                var cache = Get(saveManager, "playerCache");
                if (cache == null) { how = "playerCache is null"; return null; }
                var t = cache.GetType();
                MethodInfo contains = null, item = null;
                for (var c = t; c != null && (contains == null || item == null); c = c.BaseType)
                {
                    try
                    {
                        contains = contains ?? c.GetMethod("ContainsKey", new[] { typeof(long) });
                        item = item ?? c.GetMethod("get_Item", new[] { typeof(long) });
                    }
                    catch { }
                }
                if (contains == null || item == null) { how = "playerCache has no ContainsKey/get_Item(long)"; return null; }
                if (!(bool)contains.Invoke(cache, new object[] { id })) { how = "not in playerCache"; return null; }
                var pm = item.Invoke(cache, new object[] { id });
                if (pm == null) { how = "playerCache entry is null"; return null; }
                var cm = Get(pm, "CharacterModel");
                if (cm == null) { how = "PlayerModel.CharacterModel is null"; return null; }
                long cid;
                if (!TryNum(Get(cm, "Id"), out cid) || cid != id) { how = $"cached CharacterModel has Id {Str(Get(cm, "Id"))}, not {id}"; return null; }
                return cm;
            }
            catch (Exception e)
            {
                how = $"{e.GetType().Name}: {e.Message}";
                return null;
            }
        }

        // GameCharacterModel.IsStatusSafehouseAliveAndActive(), the engine's
        // own answer to "is this merc in the safehouse". Null when the method
        // is missing or throws, which callers treat as "do not filter".
        private static bool? SafehouseAliveAndActive(object row)
        {
            try
            {
                var m = row.GetType().GetMethod("IsStatusSafehouseAliveAndActive",
                    BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance,
                    null, Type.EmptyTypes, null);
                if (m == null)
                {
                    if (!warnedNoSafehousePredicate)
                    {
                        warnedNoSafehousePredicate = true;
                        Plugin.Log.LogWarning("Elapse: GameCharacterModel has no "
                            + "IsStatusSafehouseAliveAndActive(); safehouseOnly cannot filter and "
                            + "every roster row is eligible. Reported once.");
                    }
                    return null;
                }
                var v = m.Invoke(row, null);
                return v == null ? (bool?)null : Convert.ToBoolean(v);
            }
            catch (Exception e)
            {
                if (!warnedNoSafehousePredicate)
                {
                    warnedNoSafehousePredicate = true;
                    Plugin.Log.LogWarning($"Elapse: IsStatusSafehouseAliveAndActive() threw "
                        + $"{e.GetType().Name}: {e.Message}; not filtering. Reported once.");
                }
                return null;
            }
        }

        // TagTypeId -> TagModel.RelType. DataDb.ReadTags() is the shipped table
        // (61 rows); the per-row TagData join on GameCharacterTagModel is the
        // fallback if DataDb cannot be reached from the DataLayer.
        private static Dictionary<string, long> RelTypes(object dataLayer, List<object> tags)
        {
            var map = new Dictionary<string, long>(StringComparer.Ordinal);

            object dataDb = null;
            try { dataDb = Get(dataLayer, "DataDBI"); } catch { }
            if (dataDb != null)
            {
                bool complete;
                foreach (var t in ReadRows(dataDb, "ReadTags", out complete))
                {
                    string id = Str(Get(t, "TagId"));
                    long rel;
                    if (string.IsNullOrEmpty(id)) { NoteUnreadable("TagModel", "TagId"); continue; }
                    if (!TryNum(Get(t, "RelType"), out rel)) { NoteUnreadable("TagModel", "RelType"); continue; }
                    map[id] = rel;
                }
            }
            // The shipped table carries 23 x +1 and 26 x -1. A map with no
            // non-zero entry is a reader that returned nothing usable, and
            // treating it as "everyone is neutral" would make a merc who hates
            // the contact eligible.
            if (map.Values.Any(v => v != 0)) return map;
            map.Clear();

            foreach (var t in tags)
            {
                var td = Get(t, "TagData");
                if (td == null) continue;
                string id = Str(Get(td, "TagId"));
                if (string.IsNullOrEmpty(id)) id = Str(Get(t, "TagTypeId"));
                long rel;
                if (string.IsNullOrEmpty(id) || map.ContainsKey(id)) continue;
                if (!TryNum(Get(td, "RelType"), out rel)) continue;
                map[id] = rel;
            }
            if (map.Values.Any(v => v != 0))
            {
                if (!warnedNoRelTypes)
                {
                    warnedNoRelTypes = true;
                    Plugin.Log.LogWarning("Elapse: DataDb.ReadTags() gave nothing; RelType is "
                        + "being read off GameCharacterTagModel.TagData instead. Worth reporting.");
                }
                return map;
            }

            if (!warnedNoRelTypes)
            {
                warnedNoRelTypes = true;
                Plugin.Log.LogError("Elapse: could not read TagModel.RelType from DataDb.ReadTags() "
                    + "or from GameCharacterTagModel.TagData. Mercs cannot be partitioned by "
                    + "polarity, so the stress channel does nothing rather than stress a merc "
                    + "who hates the contact.");
            }
            return null;
        }

        // ---- seeding ---------------------------------------------------------

        // splitmix64 over (a, b). The same mixer as Fatigue.StableRoll, used as
        // a full 64-bit value here because it orders a list rather than rolls
        // a percentage.
        private static ulong Mix(ulong a, ulong b)
        {
            unchecked
            {
                ulong z = a * 0x9E3779B97F4A7C15UL + b;
                z += 0x9E3779B97F4A7C15UL;
                z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9UL;
                z = (z ^ (z >> 27)) * 0x94D049BB133111EBUL;
                return z ^ (z >> 31);
            }
        }

        private static ulong Fnv1a(string s)
        {
            unchecked
            {
                ulong h = 14695981039346656037UL;
                foreach (char c in s ?? "") { h ^= c; h *= 1099511628211UL; }
                return h;
            }
        }

        // ---- database access -------------------------------------------------

        // __instance.Dac.GameDBI. The DataLayer comes back too, for DataDBI
        // (the shipped TagModel table). Both are used inside the postfix and
        // dropped; nothing here is stored past the tick.
        private static object Db(object saveManager, out object dataLayer)
        {
            dataLayer = null;
            try
            {
                var dac = Get(saveManager, "Dac");
                if (dac == null)
                {
                    Plugin.Log.LogError("Elapse: SaveManager.Dac was null on the turn tick.");
                    return null;
                }
                var db = Get(dac, "GameDBI");
                if (db == null)
                {
                    Plugin.Log.LogError("Elapse: DataLayer.GameDBI was null on the turn tick.");
                    return null;
                }
                dataLayer = dac;
                return db;
            }
            catch (Exception e)
            {
                Plugin.Log.LogError($"Elapse: reaching GameDb off SaveManager failed: {e.Message}");
                return null;
            }
        }

        // A zero-arg bulk reader, materialised, with a completeness flag. Bulk
        // readers only: a by-id reader that misses THROWS where a postfix
        // cannot see it (docs/verifying-2.7.md). `complete` is false whenever
        // the caller must not conclude anything from a row being absent.
        private static List<object> ReadRows(object db, string reader, out bool complete)
        {
            var rows = new List<object>();
            complete = false;
            object list;
            try { list = Call(db, reader, Type.EmptyTypes, new object[0]); }
            catch (Exception e)
            {
                var inner = e.InnerException ?? e;
                Plugin.Log.LogError($"Elapse: {reader}() threw {inner.GetType().Name}: {inner.Message}");
                return rows;
            }
            if (list == null)
            {
                Plugin.Log.LogWarning($"Elapse: {reader}() returned null.");
                return rows;
            }

            var shape = ListShape.For(list.GetType());
            if (shape != null && shape.Usable)
            {
                int n;
                if (!shape.TryCount(list, out n))
                {
                    // A Count that threw is not a list of zero rows. Reporting
                    // it as complete-and-empty would wipe the board snapshot.
                    Plugin.Log.LogWarning($"Elapse: {reader}() returned a list whose Count could "
                                        + "not be read; this read is partial.");
                    return rows;
                }
                for (int i = 0; i < n; i++)
                {
                    var row = shape.At(list, i);
                    if (row == null)
                    {
                        Plugin.Log.LogWarning($"Elapse: {reader}() element {i} of {n} could not be "
                                            + "read; this read is partial.");
                        return rows;
                    }
                    rows.Add(row);
                }
                complete = true;
                return rows;
            }

            var en = list as System.Collections.IEnumerable;
            if (en == null || list is string)
            {
                Plugin.Log.LogWarning($"Elapse: {reader}() returned a {list.GetType().Name} that "
                                    + "exposes neither Count/this[i] nor IEnumerable.");
                return rows;
            }
            try
            {
                foreach (var x in en)
                {
                    if (x == null)
                    {
                        // The same contract the indexer path above honours: a
                        // null element is a row that could not be read, and
                        // `complete` has to stay false so the caller does not
                        // conclude anything from a row being absent. This used
                        // to drop nulls and still report the read complete, so
                        // a board read that lost rows was recorded as a whole
                        // snapshot and a log read that lost rows advanced the
                        // high-water mark over them.
                        Plugin.Log.LogWarning($"Elapse: {reader}() enumerated a null element after "
                                            + $"{rows.Count} row(s); this read is partial.");
                        return rows;
                    }
                    rows.Add(x);
                }
                complete = true;
            }
            catch (Exception e)
            {
                Plugin.Log.LogWarning($"Elapse: enumerating {reader}() threw {e.GetType().Name} "
                                    + $"after {rows.Count} row(s); this read is partial.");
            }
            return rows;
        }

        // ---- reflection helpers ----------------------------------------------
        //
        // Local rather than reaching for Accessors, as Fatigue's are: these run a
        // few hundred times per tick, not per row of a hot reader, and keeping
        // them here keeps this file independent of the rule engine's caches.

        private static object Call(object target, string name, Type[] sig, object[] args)
        {
            if (target == null) throw new InvalidOperationException("no target for " + name);
            MethodInfo m = null;
            for (var t = target.GetType(); t != null && m == null; t = t.BaseType)
                m = t.GetMethod(name,
                    BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance,
                    null, sig, null);
            if (m == null)
                throw new MissingMethodException(target.GetType().Name + "." + name);
            return m.Invoke(target, args);
        }

        // One-argument call resolved against the ARGUMENT's own type, walking
        // up its bases — the model may be declared as its base on the method.
        // Exact parameter type wins over merely assignable, as in WriteProbe.
        private static object Call1(object db, string name, object arg)
        {
            MethodInfo m = null, loose = null;
            for (var t = db.GetType(); t != null && m == null; t = t.BaseType)
            {
                foreach (var cand in t.GetMethods(BindingFlags.Public | BindingFlags.NonPublic
                                                | BindingFlags.Instance | BindingFlags.DeclaredOnly))
                {
                    if (cand.Name != name) continue;
                    var ps = cand.GetParameters();
                    if (ps.Length != 1) continue;
                    if (ps[0].ParameterType == arg.GetType()) { m = cand; break; }
                    if (loose == null && ps[0].ParameterType.IsInstanceOfType(arg)) loose = cand;
                }
            }
            if (m == null) m = loose;
            if (m == null)
                throw new MissingMethodException(db.GetType().Name + "." + name
                    + "(" + arg.GetType().Name + ")");
            return m.Invoke(db, new[] { arg });
        }

        private static readonly Dictionary<Type, Dictionary<string, PropertyInfo>> PropCache =
            new Dictionary<Type, Dictionary<string, PropertyInfo>>();

        // A model's columns live on its *Base type, not on the leaf, so this
        // walks the hierarchy asking each level for its declared members.
        private static PropertyInfo Prop(Type type, string name)
        {
            if (type == null) return null;
            Dictionary<string, PropertyInfo> byName;
            if (!PropCache.TryGetValue(type, out byName))
                PropCache[type] = byName = new Dictionary<string, PropertyInfo>(StringComparer.Ordinal);

            PropertyInfo p;
            if (byName.TryGetValue(name, out p)) return p;

            for (var t = type; t != null && t != typeof(object) && p == null; t = t.BaseType)
            {
                try
                {
                    p = t.GetProperty(name, BindingFlags.Public | BindingFlags.NonPublic
                                          | BindingFlags.Instance | BindingFlags.DeclaredOnly);
                }
                catch { }
            }
            byName[name] = p;                       // misses are cached too
            return p;
        }

        private static object Get(object row, string name)
        {
            if (row == null) return null;
            var p = Prop(row.GetType(), name);
            if (p != null) { try { return p.GetValue(row); } catch { return null; } }
            // Interop exposes il2cpp fields as properties, but a plain field
            // costs nothing to check and playerCache is the one member here
            // whose shape was read from metadata rather than exercised.
            try
            {
                for (var t = row.GetType(); t != null && t != typeof(object); t = t.BaseType)
                {
                    var f = t.GetField(name, BindingFlags.Public | BindingFlags.NonPublic
                                           | BindingFlags.Instance | BindingFlags.DeclaredOnly);
                    if (f != null) return f.GetValue(row);
                }
            }
            catch { }
            return null;
        }

        private static bool Set(object row, string name, object value)
        {
            if (row == null) return false;
            var p = Prop(row.GetType(), name);
            if (p == null)
            {
                Plugin.Log.LogWarning($"Elapse: no column named {name} on {row.GetType().Name}.");
                return false;
            }
            if (!p.CanWrite)
            {
                Plugin.Log.LogWarning($"Elapse: {name} is read-only on {row.GetType().Name}.");
                return false;
            }
            try
            {
                p.SetValue(row, value is string
                    ? value
                    : Convert.ChangeType(value,
                        Nullable.GetUnderlyingType(p.PropertyType) ?? p.PropertyType,
                        CultureInfo.InvariantCulture));
                return true;
            }
            catch (Exception e)
            {
                Plugin.Log.LogWarning($"Elapse: setting {name} threw {e.GetType().Name}: "
                                    + e.Message);
                return false;
            }
        }

        // A column that has to be a number for the row to be usable. Records
        // its name on failure instead of quietly reading 0.
        private static long Col(object row, string name, List<string> missing)
        {
            long n;
            if (TryNum(Get(row, name), out n)) return n;
            missing.Add(name);
            return 0;
        }

        private static void NoteUnreadable(string model, string column)
        {
            if (!unreadableWarned.Add(model + "." + column)) return;
            Plugin.Log.LogWarning($"Elapse: {model}.{column} came back null or unconvertible on at "
                + "least one row. Rows missing it are refused rather than read as 0. Reported once.");
        }

        private static long Num(object v)
        {
            long n;
            return TryNum(v, out n) ? n : 0;
        }

        // Num() collapses "could not read" into 0. On any path that decides a
        // write, or that keys a merc, that difference is the one that matters.
        private static bool TryNum(object v, out long n)
        {
            n = 0;
            if (v == null) return false;
            try { n = Convert.ToInt64(v, CultureInfo.InvariantCulture); return true; }
            catch { return false; }
        }

        private static string Str(object v)
        {
            try { return v == null ? "" : v.ToString(); } catch { return ""; }
        }
    }
}
