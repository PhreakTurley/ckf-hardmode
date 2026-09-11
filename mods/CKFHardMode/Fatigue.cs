// Fatigue — mission fatigue, Running Empty -> Off-Duty.
//
// The design is docs/character-fatigue.md; this file is its implementation and
// deviates from it in exactly three places, all of them David's rulings of
// 2026-08-30 and all recorded in that doc's section 10:
//
//   1. The first-stage trait id is a config key. 2009 Running Empty is the
//      default; 2007 Checked Out is the milder alternative and swaps in without
//      a rebuild. Both are TraitClass 6 and sit in their own TraitGroup, so
//      neither collides with 2014 Off-Duty.
//   2. `applyOnMissionFailure` is gone, key and code. Run45 established that a
//      lost mission writes no GameScore row of any kind, so the hook below
//      never fires on defeat and a failed mission costs no fatigue. Building it
//      would mean a second patch on
//      View_MissionRoomDefeat_Main.ProcessCharactersAfterDefeat with its own
//      roster source; that is not in this mod.
//   3. The Cyber Knight sits inside the min/max clamp like anyone else. He
//      still rolls on his own odds and takes his own duration.
//
// Two things were added after the first build, on David's rulings of the same
// day, and neither is in the design doc's sections 1-9:
//
//   4. POWER-LEVEL SCALING. chancePercent, minAffected, maxAffected and
//      durationDays can each vary with the mission's PowerLevel, given as
//      anchor points that interpolate. See the byPowerLevel section below.
//   5. WOUND RESIST MITIGATION. A merc's Wound Resist is subtracted from their
//      chance, one point per percentage point, floored at minChancePercent.
//      See the WoundRes section below.
//
// Two more on 2026-09-10:
//
//   6. SOLO MISSIONS ARE EXEMPT. David's ruling. A mission whose roster is one
//      character runs none of this: no roll, no escalation, nothing written.
//      See the check at the top of Resolve.
//   7. WOUND RESIST NO LONGER DEPENDS ON THE JOINED EffectData. Run63 rolled
//      four mercs at "no resist" with no warning. AddRows skipped any row whose
//      EffectData was null without a word, and only the trait reader was ever
//      shown to fill that join (Run44). A row without it now has its effect
//      read from DataDb, and every roll line says how many rows each reader
//      returned and how their effects were found. See ResistFor.
//   8. ARMOUR COUNTS TOWARD WOUND RESIST. David's ruling, reversing the
//      2026-08-30 one that kept gear out. Classification 9 ArmorEffect is no
//      longer dropped, and the merc's armour is read as a fifth source through
//      ReadGameArmorByCharacter. See the "armor" ResistSource.
//
// THE FLAT VALUES ARE GONE. David's ruling, 2026-09-07. Every setting that had
// a byPowerLevel analogue is off the config surface: runningEmpty.chancePercent,
// .durationDays, .minAffected, .maxAffected, runningEmpty.knight.chancePercent,
// runningEmpty.knight.durationDays, offDuty.durationDays and
// offDuty.knight.durationDays. A one-anchor curve at power level 1 does the same
// job, because an anchor holds below the level it names. What this file used to
// call "the base layer" is now the curves and nothing else:
//
//   * The properties that parse those eight keys are STILL HERE, marked legacy
//     below, because Load refuses any file carrying a key that maps to no
//     member and deleting them would make every existing player's
//     ckf.hardmode.json fail to load. They are parsed and never read. A file
//     that carries one gets one log line at load naming what it found.
//   * Curve() no longer bails out on an unreadable PowerLevel. A PowerLevel of
//     0 falls into `powerLevel <= pts[0].Key` and takes the curve's LOWEST
//     ANCHOR, which is what makes a one-anchor PL 1 curve behave exactly like
//     the flat value it replaces, in every case including that one. The
//     once-only warning stays and now says that is what happened.
//   * Validate refuses a runningEmpty.byPowerLevel that is absent or empty
//     while "enabled" is true. Nothing backs it up any more.
//   * A resolver whose curve names no value for the field it needs returns
//     "no value" rather than a number nobody configured, and the roll or the
//     write it feeds does not happen and is logged. See the four resolvers.
//
// THREE FIXES FROM THE 2.9.1 CODE REVIEW, all before the first launch. Each has
// offline checks that fail without it; see tests/fatigue/ and
// project memory `fatigue-code-review`:
//
//   1. Escalation now deletes the first-stage trait ONLY after the Off-Duty
//      insert succeeded. It used to delete unconditionally, so a refused insert
//      left the merc carrying nothing at all and the mission REMOVED fatigue
//      instead of escalating it.
//   2. The Wound Resist dedupe covers all four readers, not just trait ->
//      effect. Implants are the source that decides this mechanic's balance,
//      and an implant mirrored into the effect table used to count twice.
//   3. The minChancePercent floor bounds what RESIST takes away and no longer
//      raises a chance that was already at or below it. A configured 0 used to
//      come back as 5.
//
// FOUR MORE FIXES FROM THE SAME REVIEW, shipped as 2.9.2 and again before the
// first launch. Each has offline checks that fail without it:
//
//   4. The section 4.1 double-fire guard no longer trusts session memory alone.
//      On a hit it asks the DATABASE whether the rows that resolution wrote are
//      still there — every row this file writes is stamped CreatedTurn = the
//      mission's turn, so a matching row is that resolution's own evidence.
//      Present means a genuine second type-16 row and the guard blocks. Absent
//      means the save was rolled back under us, so the mission resolves again
//      instead of a reload silently ERASING fatigue. The safehouse total also
//      moved from once per session to once per mission, so a Triage Clinic
//      built mid-session takes effect and another save slot does not inherit
//      the first one's number. A speculative postfix on
//      ViewModel_GameManagement.LoadGame/LoadGameSlot clears the session
//      statics outright; the interop assembly is stubs, so whether that is the
//      real load seam is a question only the log answers.
//   5. Validate reaches the curve anchors. CheckLevels covers durationDays,
//      minAffected and maxAffected as well as chancePercent, knight.durationDays
//      is range-checked on both blocks, and a sweep over PL 1-20 rejects a curve
//      whose ceiling drops below its floor at any level.
//   6. offDuty duration curves. offDuty.byPowerLevel and
//      offDuty.knight.byPowerLevel both work and both interpolate durationDays,
//      matching David's ruling 4; the other three fields are meaningless there
//      and are warned about rather than ignored. David's call, 2026-08-30.
//   7. The catch around ReadGameCharacter logs. It was the only silent catch in
//      the file, and a renamed reader used to cost every merc IsKnight and
//      DisplayName with a blank name in the log as the only tell. THAT COVERED
//      THE THROWING CASE ONLY, and this note used to claim the hole was closed:
//      a reader that RETURNED NULL instead of throwing produced the same blank
//      name and the same unrecognised Knight with no log line at all. Both the
//      throw and the null return are reported now.
//
// THIS IS THE FIRST SUBSYSTEM IN THIS PLUGIN THAT WRITES TO THE SAVE.
// Everything else here is read-time — GetRow postfixes, in-memory row copies,
// prefixes that adjust an input before the game computes with it. This inserts
// and deletes GameCharacterTrait rows. What makes that acceptable rather than
// reckless is that all of it was proven against a live save first, by
// CKFDataDump's [TraitProbe] over four sessions:
//
//   Run44  a constructed row inserts and both readers see it
//   Run45  the same insert nested inside the InsertGameScore postfix, while
//          the game's own insert is still unwinding through SqlNado
//   Run46  the row survives a save, a load of another slot and a return, and
//          the game's own SaveManager.ProcessTraits expires it on schedule
//   Run47  the whole resolution order below, over a real four-merc roster:
//          two inserts and a delete in one nested postfix, zero errors, and
//          deterministic rolls matching a prediction made before the run
//
// So the mod writes the row, sets ExpiresTurn, and the engine owns the rest of
// its life cycle. No new table, no new column, no side file, and no tick of our
// own. Uninstalling leaves at most a few live traits that expire by themselves.
//
// WHAT THIS DELIBERATELY DOES NOT DO. It does not filter
// ReadGameCharactersAvailableForMission. Roster restriction is the engine's
// job, off Off-Duty's SpecialCode 90 BlockMissions, and doing it here would
// also throw away the game's own "unless required by mission" story override.
// It does not touch MedicalTurn; that route is shelved in
// docs/character-fatigue-injury-route.md and is not a fallback. It does not
// force a save: GameDb is a live database and a save slot is a snapshot of it,
// so a grant persists exactly when the player's own progress does, which is the
// least surprising behaviour available.

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
    // WHERE THE POWER LEVEL COMES FROM
    //
    // GameDb.ReadGameMissionActive() -> GameMissionModel, zero-arg, and its
    // PowerLevel column is the mission's effective level — the one [PowerLevel]
    // lifts past the stock ceiling of 10. PowerLevelUnscaled is the pre-scaling
    // number and is NOT what this uses.
    //
    // The type-16 and type-19 score rows carry no mission identity at all:
    // both have ScoreTargetId 0 and an empty ScoreKey across all 92 missions in
    // the shipped save. Only type 8 AcceptMission and type 11 StartRoom carry a
    // ScoreKey, and neither carries a power level. So the level has to be read
    // off the active mission, and it is read at Phase A — the first type-19 row
    // — because by the time the type-16 terminator lands the game may already
    // have retired the mission. If Phase A missed it, Phase B tries once more,
    // and if that also fails the level stays 0, every curve returns its LOWEST
    // ANCHOR for it, and the log says so once.
    //
    // WHAT WOUND RESIST IS, AND WHERE IT LIVES
    //
    // The Triage Clinic (ModuleClassId 18, module types 71-74) grants exactly
    // two things: InjuryTime -25/-30/-35/-40 and WoundRes 10/15/20/30, by
    // upgrade level. WoundRes is therefore the stat, and it is a plain integer
    // column on EffectModel and on SafehouseModuleModel.
    //
    // 144 of the 1,678 EffectModel rows carry a non-zero WoundRes. By
    // EffectClassification — whose values are an EXPLICIT enum, not declaration
    // order; reading them as declaration order mislabels every one of them:
    //
    //     1 TalentBuff            9 rows   -50..+50    limited-time
    //     3 Backstory            40 rows   -50..+25    always-active
    //     4 Wound                 4 rows   -20..-10    limited-time
    //     7 Cyberware            64 rows   -25..+25    always-active
    //     9 ArmorEffect          22 rows    +3..+30    always-active, counted since 2026-09-10
    //    10 TalentDebuff          1 row    -25..-25    limited-time
    //    12 MutationTempTrait     4 rows  -100..+50    limited-time
    //
    // CORRECTION, 2026-09-10: gear was out on David's 2026-08-30 ruling and
    // classification 9 was dropped wherever it arrived. He reversed that on
    // 2026-09-10: armour now counts, read from the merc's GameArmor row, and a
    // classification-9 effect arriving through any other reader counts too
    // (once, through the same union). Job nodes are included for completeness
    // and contribute nothing: 0 of 1,525 shipped JobNodeModel rows point at an
    // effect carrying WoundRes.
    //
    // CYBERWARE RUNS NEGATIVE, AND THAT IS THE POINT. 51 of the 83 implants
    // that carry WoundRes are negative. Every merc in David's save is between
    // -10 and -39 from implants alone, so against a 25% base a chromed crew
    // rolls 35-64% rather than 25%. Ruled deliberate, 2026-08-30: chrome makes
    // you tire faster. The same ruling kept armour from buying it back; that
    // half was reversed on 2026-09-10 and armour now counts.
    //
    // The readers, all per-character. CORRECTION, 2026-09-10: this comment
    // used to say all four return rows carrying a joined EffectData "exactly
    // as GameCharacterTraitModel does". That was measured for the trait reader
    // only (Run44) and assumed for the other three, and AddRows skipped a null
    // EffectData silently, so the assumption could fail with no log line.
    // Run63 is the first live run of this path: four mercs, resist 0 each, no
    // warning. A row without the join now has its effect read from DataDb
    // through its own content row (ResistSource below).
    //
    //     ReadGameCharacterTraitsByCharacter(Int64)  already called by Phase B
    //     ReadGameCharacterEffects(Int64)
    //     ReadGameCharacterImplants(Int64)
    //     ReadGameCharacterJobNodes(Int64)
    //     ReadGameArmorByCharacter(Int64)            one row, not a list; 2026-09-10
    //
    // plus the safehouse, which is global rather than per-merc.
    //
    // TIMED VERSUS ALWAYS-ACTIVE. Two independent axes separate them, and both
    // are definitive. EffectClassification says what kind of thing granted the
    // effect (the table above). GameCharacterTraitModel.ExpiresTurn says
    // whether one granted row is timed: non-zero is timed, zero is permanent,
    // which is the game's own predicate — SaveManager.ProcessTraits sweeps
    // WHERE ExpiresTurn != 0 AND ExpiresTurn <= ?. Both halves count toward the
    // total; the split is logged rather than configured, because David asked
    // whether it could be separated, not for a switch.

    internal static class Fatigue
    {
        // 4 turns = 1 day. RuleModel 40 "Max Injury Time" is 100 turns and the
        // game describes it as "25 days default", which is where this comes
        // from. Run46 confirmed it: a 1-day grant at turn 1386 expired at 1390.
        private const long TurnsPerDay = 4;

        private const long ScoreTypeMissionComplete = 16;
        private const long ScoreTypeCharacterOnMission = 19;

        private const string GameDbTypeName = "RPG.Database.GameDb";

        // The id range RowClone reserves for the rows its own rules construct —
        // RowClone.cs's ReservedFrom. Mirrored rather than referenced because it
        // is private there and this file may not reach into it; if that number
        // moves, this one has to move with it. Validate uses it to catch a
        // traitId typo that lands up there.
        private const long CloneReservedFrom = 900000;

        // ViewModel_GameManagement.LoadGame(CoreGameDataModel) and
        // .LoadGameSlot(CoreGameDataModel, CoreGameSaveSlotModel), both public
        // instance void. Read out of CoreRPG_v1.dll's TypeDef table: they are
        // the only two methods in the assembly whose names describe loading a
        // saved game. Whether either actually fires on the path the player
        // takes is unverifiable offline and is what AfterLoadGame's log line is
        // for.
        private const string GameManagementTypeName = "ViewModel_GameManagement";
        private const string TraitModelTypeName = "RPG.Database.Models.GameCharacterTraitModel";

        // EffectClassification, read out of the metadata Constant table rather
        // than assumed from declaration order. Only the ones this file reasons
        // about are named.
        private const long ClassWound = 4;
        private const long ClassArmorEffect = 9;      // gear; counted since 2026-09-10
        private const long ClassMutationTempTrait = 12;
        private const long ClassMutationTempTraitFace = 15;

        // Classifications whose effect is inherently limited-time. Everything
        // else counts as always-active. A trait row also counts as timed when
        // its own ExpiresTurn is non-zero, whatever its classification says.
        private static readonly HashSet<long> TimedClasses = new HashSet<long>
        {
            1,  // TalentBuff
            2,  // TalentBooster
            ClassWound,
            8,  // TalentBoosterDebuff
            10, // TalentDebuff
            ClassMutationTempTrait,
            13, // MissionAdvantageBuff
            14, // MissionAdvantageDebuff
            ClassMutationTempTraitFace,
        };

        private static Options o;
        private static bool active;

        // Our own writes call GameDb methods on a GameDb we hold a postfix on.
        // RowClone carries the same flag for the same reason.
        [ThreadStatic] private static bool reentrant;

        // Phase A's roster, and the section 4.1 guard. The guard is keyed on the
        // mission's turn AND its sorted roster, not the turn alone. What that
        // actually buys is narrower than this comment used to claim: two missions
        // completing on one turn are told apart only when their SQUADS differ.
        // The SAME squad on two missions in one turn produces the identical key,
        // so the second one is blocked as a double-fire and its fatigue is lost
        // silently. The key is left as it is — the type-16 and type-19 rows carry
        // no mission identity to key on (see the note above InsertGameScore), so
        // there is nothing better available here.
        private static readonly List<long> pendingRoster = new List<long>();
        private static readonly HashSet<string> resolved =
            new HashSet<string>(StringComparer.Ordinal);

        // Keys marked resolved whose write loop never reached its end. Cleared
        // at the end of the loop; see the mark site in Resolve.
        private static readonly HashSet<string> interrupted =
            new HashSet<string>(StringComparer.Ordinal);

        // The GameTurn carried by the type-19 rows now sitting in pendingRoster,
        // -1 when nothing is pending. This is the session-state fallback for a
        // reload the LoadGame hook did not catch; the rule and its holes are
        // written out at the Phase A site that uses it.
        private static long pendingTurn = -1;

        private static readonly Random rng = new Random();

        // The active mission's PowerLevel, captured at Phase A because the
        // mission may already be retired by the time the terminator lands.
        // 0 means "not read". Since 2026-09-07 that is not a special case in
        // the curve any more: 0 is below every sane anchor, so Curve() clamps it
        // to the lowest one. Resolve still says so once.
        private static long pendingPowerLevel;

        // Log-once flags, so a session that cannot read the power level or that
        // finds the game writing both a trait row and an effect row says so
        // exactly once instead of on every mission.
        private static bool warnedNoPowerLevel, notedTraitEffectOverlap, warnedNoCharacterReader;

        // (model, column) pairs already reported as unreadable, and lists already
        // reported as partial. Elapse.cs carries the same set for the same
        // reason: a renamed column costs one log line, not one per row per
        // mission.
        private static readonly HashSet<string> unreadableWarned =
            new HashSet<string>(StringComparer.Ordinal);

        // The safehouse total is re-read once per MISSION, not once per session:
        // a Triage Clinic built or upgraded mid-session has to take effect, and
        // loading another save slot must not inherit the first slot's number.
        // It is still one read per mission rather than one per merc.
        private static int safehouseResist;
        private static bool safehouseRead;
        private static int loggedSafehouseValue = int.MinValue;

        // DataDb rows fetched for resist rows that arrived without their joined
        // EffectData, keyed "<reader>:<id>". Misses are cached as null so a
        // failing lookup costs one call per mission, not one per merc. Cleared
        // with safehouseRead, once per mission and on a load.
        private static readonly Dictionary<string, object> lookupCache =
            new Dictionary<string, object>(StringComparer.Ordinal);

        // Once-per-session notes for the resist readers, keyed by source name.
        private static readonly HashSet<string> resistNoted =
            new HashSet<string>(StringComparer.Ordinal);

        // ---- config ----------------------------------------------------------

        // EVERY CONFIG TYPE BELOW CARRIES AN `Unknown` BUCKET. [JsonExtensionData]
        // collects the keys that map to no member of its type, which
        // System.Text.Json otherwise drops without a word: "chancepercent" with
        // a lower-case p used to vanish and leave ChancePercent at its shipped
        // default of 25, so the mod wrote traits at that rate rather than the
        // one in the file, with no log line anywhere. Load walks these buckets
        // and refuses the file. Matching stays case-SENSITIVE on purpose — a
        // misspelled key has to land in the bucket to be reported, and turning
        // on case-insensitive matching would hide exactly the typo this catches.
        //
        // A Dictionary<string, JsonElement> rather than the serializer option
        // that refuses unmapped members outright: that option arrived in .NET 8
        // and this project targets net6.0 (see CKFHardMode.csproj), so it does
        // not exist here.

        // One anchor point on the power-level curve. Every field is optional and
        // each one interpolates independently over the anchors that name it, so
        // a curve can shape the chance across all 20 levels while leaving the
        // ceiling flat. A field named by NO anchor of any applicable curve has
        // no value at all now that the flat settings are gone; what each
        // resolver does about that is written out at the resolvers.
        private sealed class LevelPoint
        {
            [JsonPropertyName("chancePercent")] public int? ChancePercent { get; set; }
            [JsonPropertyName("durationDays")]  public int? DurationDays { get; set; }
            [JsonPropertyName("minAffected")]   public int? MinAffected { get; set; }
            [JsonPropertyName("maxAffected")]   public int? MaxAffected { get; set; }
            [JsonExtensionData] public Dictionary<string, JsonElement> Unknown { get; set; }
        }

        // Used by BOTH runningEmpty.knight and offDuty.knight.
        private sealed class KnightBlock
        {
            // LEGACY AND IGNORED, 2026-09-07. runningEmpty.knight.chancePercent
            // and runningEmpty.knight.durationDays / offDuty.knight.durationDays
            // are off the config surface; the Knight's numbers come from his
            // byPowerLevel curve, or the general one where he has none. These
            // two properties exist ONLY so a file written before the removal
            // still parses — Load refuses any file with a key that maps to no
            // member, so deleting them would lock every existing player out of
            // their own config. Nothing reads them; LegacyKeys names them in one
            // log line when a file carries them. offDuty.knight.chancePercent
            // was never a real setting and is warned about separately in
            // Validate, because escalation is not a roll.
            [JsonPropertyName("chancePercent")] public int? ChancePercent { get; set; }
            [JsonPropertyName("durationDays")]  public int? DurationDays { get; set; }
            [JsonPropertyName("byPowerLevel")]
            public Dictionary<string, LevelPoint> ByPowerLevel { get; set; }
            [JsonExtensionData] public Dictionary<string, JsonElement> Unknown { get; set; }
        }

        // A merc's Wound Resist, summed and subtracted from their chance one
        // point per percentage point. Positive resist protects; negative resist
        // — which is most cyberware — makes fatigue more likely.
        private sealed class WoundResistBlock
        {
            [JsonPropertyName("enabled")] public bool Enabled { get; set; } = true;

            // The chance can never fall below this however much resist a merc
            // carries, so nobody is ever fully immune and minAffected always
            // has someone it can reach for.
            [JsonPropertyName("minChancePercent")] public int MinChancePercent { get; set; } = 5;
            [JsonExtensionData] public Dictionary<string, JsonElement> Unknown { get; set; }
        }

        private sealed class RunningEmptyBlock
        {
            [JsonPropertyName("traitId")]       public long TraitId { get; set; } = 2009;

            // LEGACY AND IGNORED, 2026-09-07. chancePercent, durationDays,
            // minAffected and maxAffected are off the config surface; all four
            // live in byPowerLevel and nowhere else. Kept, nullable and with no
            // initialiser, for the same two reasons throughout: an old file has
            // to keep parsing (Load refuses a key that maps to no member), and
            // nullable is the only way to tell "the file set it" from "the file
            // did not", which is what LegacyKeys reports. NOTHING READS THEM.
            [JsonPropertyName("chancePercent")] public int? ChancePercent { get; set; }
            [JsonPropertyName("durationDays")]  public int? DurationDays { get; set; }
            [JsonPropertyName("minAffected")]   public int? MinAffected { get; set; }
            [JsonPropertyName("maxAffected")]   public int? MaxAffected { get; set; }

            [JsonPropertyName("byPowerLevel")]
            public Dictionary<string, LevelPoint> ByPowerLevel { get; set; }
            [JsonPropertyName("knight")]        public KnightBlock Knight { get; set; }
            [JsonExtensionData] public Dictionary<string, JsonElement> Unknown { get; set; }
        }

        private sealed class OffDutyBlock
        {
            [JsonPropertyName("traitId")]            public long TraitId { get; set; } = 2014;

            // LEGACY AND IGNORED, 2026-09-07. offDuty.durationDays is off the
            // config surface; the Off-Duty duration lives in byPowerLevel. Kept
            // so an old file parses; nothing reads it.
            [JsonPropertyName("durationDays")]       public int? DurationDays { get; set; }

            [JsonPropertyName("clearsRunningEmpty")] public bool ClearsRunningEmpty { get; set; } = true;
            // Off-Duty duration scales with mission power level too — David's
            // ruling 4, wired in 2.9.2, and since 2026-09-07 the only place it
            // lives. Only durationDays means anything on these anchors; the
            // other three fields belong to the roll, which escalation does not
            // make.
            [JsonPropertyName("byPowerLevel")]
            public Dictionary<string, LevelPoint> ByPowerLevel { get; set; }
            [JsonPropertyName("knight")]             public KnightBlock Knight { get; set; }
            [JsonExtensionData] public Dictionary<string, JsonElement> Unknown { get; set; }
        }

        private sealed class Options
        {
            [JsonPropertyName("enabled")]            public bool Enabled { get; set; } = true;
            [JsonPropertyName("runningEmpty")]       public RunningEmptyBlock RunningEmpty { get; set; }
            [JsonPropertyName("offDuty")]            public OffDutyBlock OffDuty { get; set; }
            [JsonPropertyName("woundResist")]        public WoundResistBlock WoundResist { get; set; }
            [JsonPropertyName("deterministicRolls")] public bool DeterministicRolls { get; set; } = true;
            [JsonPropertyName("logGrants")]          public bool LogGrants { get; set; } = true;
            [JsonExtensionData] public Dictionary<string, JsonElement> Unknown { get; set; }
        }

        // ---- init ------------------------------------------------------------

        public static void Init(Harmony harmony)
        {
            // 3.0: one gate, not two. [Fatigue] Enabled is gone from
            // ckf.hardmode.cfg and "enabled" in the "fatigue" section is the
            // whole chain, so the file is read first and the switch is read out
            // of it.
            o = Load();
            if (o == null) return;                       // Load already said why

            if (!o.Enabled)
            {
                Plugin.Log.LogInfo("Fatigue: \"enabled\": false in the \"" + ConfigDoc.Fatigue
                                 + "\" section of " + ConfigDoc.FileName + " — no hooks "
                                 + "installed, nothing written.");
                return;
            }
            if (!Validate()) return;

            int patched = Patch(harmony, GameDbTypeName, "InsertGameScore",
                                nameof(AfterInsertGameScore));
            if (patched == 0)
            {
                Plugin.Log.LogError("Fatigue: could not patch GameDb.InsertGameScore, which is "
                    + "the only hook this feature has. Nothing will happen. Point CKFDataDump's "
                    + "[Diagnostics] DumpMembers at " + GameDbTypeName + " and compare.");
                return;
            }

            // Fail here rather than at the first mission completion, four hours
            // into a session, inside a nested postfix.
            if (ResolveType(TraitModelTypeName) == null)
            {
                Plugin.Log.LogError($"Fatigue: could not resolve {TraitModelTypeName}. Without it "
                    + "no trait row can be built, so the feature is off rather than half on.");
                return;
            }

            // The save-load seam, and the only speculative patch in this file.
            // The interop assembly is stubs — every body is a native invoke, so
            // no call graph can be read out of it offline — and these two are
            // the only methods in it that name loading a game. If they are the
            // wrong ones, or the game reloads by restarting the process, this
            // patches nothing and says so; the section 4.1 guard checks the
            // database rather than this hook, so nothing depends on the guess.
            // The log line below is what the first play session answers it with.
            int loadHooks = Patch(harmony, GameManagementTypeName, "LoadGame",
                                  nameof(AfterLoadGame))
                          + Patch(harmony, GameManagementTypeName, "LoadGameSlot",
                                  nameof(AfterLoadGame));
            if (loadHooks == 0)
                Plugin.Log.LogWarning($"Fatigue: could not patch {GameManagementTypeName}"
                    + ".LoadGame/LoadGameSlot, so no hook clears this session's state when you "
                    + "load a save. Three things stand in for it: the double-fire guard re-checks "
                    + "the database on every hit, so a reload still resolves correctly; the "
                    + "safehouse total is re-read once per mission; and a pending roster is "
                    + "dropped when a mission row arrives on a different turn, which catches every "
                    + "reload except one landing on the same turn. Worth reporting.");

            active = true;

            Plugin.Log.LogWarning("Fatigue: ACTIVE, and this subsystem WRITES TO YOUR SAVE.");
        }

        // 3.0: the text comes from ConfigDoc — one merged document, one section
        // each. Only the SOURCE of the text changed; the parse, the strays
        // check, the defaulting and every error path below are as they were.
        // `path` is only interpolated into messages.
        private static Options Load()
        {
            var path = ConfigDoc.Where(ConfigDoc.Fatigue);
            try
            {
                var text = ConfigDoc.SectionText(ConfigDoc.Fatigue);
                if (text == null)
                {
                    // AGENTS.md §3: an absent section and an unreadable document
                    // are different findings and do not share a log level.
                    //
                    // CORRECTION, 2026-09-07. This used to end "delete
                    // BepInEx/config/ckf.hardmode.json and relaunch — it is
                    // written back whenever it is absent". That was true while
                    // the DLL carried the defaults as embedded resources. It
                    // does not carry them now: they ship as loose files in the
                    // release zip, nothing writes one back, and following that
                    // advice would delete the player's whole config surface
                    // with no way for the mod to restore it. The zip is the
                    // place to restore from.
                    var why = $"Fatigue: {ConfigDoc.WhyNo(ConfigDoc.Fatigue)}, so there are no "
                        + "odds and no durations to work from. Doing nothing. To start again "
                        + "from the values the mod ships, extract BepInEx\\config from the "
                        + "release zip over your game folder; that is where "
                        + ConfigDoc.FileName + " comes from. Nothing writes it back on its own.";
                    if (ConfigDoc.CouldNotRead) Plugin.Log.LogError(why);
                    else Plugin.Log.LogWarning(why);
                    return null;
                }

                // No case-insensitive matching: see the note above the config
                // types. A key that maps to no member lands in that type's
                // Unknown bucket and is refused below rather than dropped.
                var opts = new JsonSerializerOptions
                {
                    ReadCommentHandling = JsonCommentHandling.Skip,
                    AllowTrailingCommas = true
                };
                var f = JsonSerializer.Deserialize<Options>(text, opts);
                if (f == null)
                {
                    Plugin.Log.LogError($"Fatigue: {path} parsed to nothing. Doing nothing.");
                    return null;
                }

                // One line per unrecognised key, naming the key and the block it
                // was written in. A dropped key does not fail loudly on its own:
                // it leaves that setting at its DEFAULT, and a chancePercent
                // that never arrived means the shipped 25% whatever the file
                // says, so this refuses the file instead.
                var strays = UnknownKeys(f);
                if (strays.Count > 0)
                {
                    foreach (var stray in strays)
                        Plugin.Log.LogError($"Fatigue: {path}: {stray}.");
                    Plugin.Log.LogError("Fatigue: keys are case-sensitive and every one above was "
                        + "IGNORED, leaving that setting at its built-in default — \"chancepercent\" "
                        + "is not \"chancePercent\", and the chance would have stayed 25. The "
                        + "feature is OFF rather than running on defaults nobody chose; fix the "
                        + "key(s) and restart.");
                    return null;
                }

                f.RunningEmpty = f.RunningEmpty ?? new RunningEmptyBlock();
                f.OffDuty = f.OffDuty ?? new OffDutyBlock();
                f.WoundResist = f.WoundResist ?? new WoundResistBlock();

                // The eight flat settings removed on 2026-09-07 still PARSE, so
                // an old file loads instead of being refused for keys that map
                // to no member. They are not read, and a setting that is read by
                // nothing and reported by nothing is exactly the silent failure
                // the Unknown buckets above exist to prevent. So: one line, at
                // load, naming every one the file actually carries.
                var legacy = LegacyKeys(f);
                if (legacy.Count > 0)
                    Plugin.Log.LogWarning($"Fatigue: {path} still carries "
                        + string.Join(", ", legacy) + ". Those settings were removed on "
                        + "2026-09-07 and are IGNORED — the matching byPowerLevel curve is what "
                        + "applies, at every power level including one that could not be read. "
                        + "They are still accepted so an older file keeps loading; deleting them "
                        + "changes nothing. A single anchor at power level 1 is how a flat value "
                        + "is written now.");
                return f;
            }
            catch (JsonException je)
            {
                // Malformed JSON — a missing brace, a number where a block
                // belongs, a string where a number does. A misspelled KEY does
                // not come through here; it is collected above. JsonException
                // carries the position in Path, which is what turns "somewhere
                // in the file" into a line to look at. Returning null leaves the
                // feature OFF.
                Plugin.Log.LogError($"Fatigue: {path} is not valid JSON: {je.Message}"
                    + (string.IsNullOrEmpty(je.Path) ? "" : $" (at {je.Path})")
                    + " Doing nothing.");
                return null;
            }
            catch (Exception e)
            {
                // Never throw past Init. A malformed sidecar turns the feature
                // off; it does not take the plugin with it.
                Plugin.Log.LogError($"Fatigue: could not read {path}: {e.GetType().Name}: "
                                  + e.Message + ". Doing nothing.");
                return null;
            }
        }

        // Every key in the file that mapped to no member, as finished sentences
        // naming the key and the block. Walks the Unknown buckets by hand
        // because there are only ten places one can appear and a reflective walk
        // over the graph would be harder to check than the list itself.
        private static List<string> UnknownKeys(Options f)
        {
            var bad = new List<string>();
            if (f == null) return bad;

            AddUnknown(f.Unknown, "top level of the file", bad);

            var re = f.RunningEmpty;
            if (re != null)
            {
                AddUnknown(re.Unknown, "runningEmpty block", bad);
                AddUnknownLevels(re.ByPowerLevel, "runningEmpty.byPowerLevel", bad);
                if (re.Knight != null)
                {
                    AddUnknown(re.Knight.Unknown, "runningEmpty.knight block", bad);
                    AddUnknownLevels(re.Knight.ByPowerLevel, "runningEmpty.knight.byPowerLevel",
                                     bad);
                }
            }

            var od = f.OffDuty;
            if (od != null)
            {
                AddUnknown(od.Unknown, "offDuty block", bad);
                AddUnknownLevels(od.ByPowerLevel, "offDuty.byPowerLevel", bad);
                if (od.Knight != null)
                {
                    AddUnknown(od.Knight.Unknown, "offDuty.knight block", bad);
                    AddUnknownLevels(od.Knight.ByPowerLevel, "offDuty.knight.byPowerLevel", bad);
                }
            }

            if (f.WoundResist != null)
                AddUnknown(f.WoundResist.Unknown, "woundResist block", bad);

            return bad;
        }

        // Every one of the eight removed flat settings that this file actually
        // carries, named by its full config path. Walked by hand for the same
        // reason UnknownKeys is: eight places, and the list is easier to check
        // than a reflective walk would be.
        //
        // offDuty.knight.chancePercent is deliberately NOT here. It was never a
        // real setting — escalation is not a roll — and Validate has its own
        // warning for it, which says why rather than "removed on 2026-09-07".
        private static List<string> LegacyKeys(Options f)
        {
            var found = new List<string>();
            if (f == null) return found;

            var re = f.RunningEmpty;
            if (re != null)
            {
                if (re.ChancePercent.HasValue) found.Add("runningEmpty.chancePercent");
                if (re.DurationDays.HasValue)  found.Add("runningEmpty.durationDays");
                if (re.MinAffected.HasValue)   found.Add("runningEmpty.minAffected");
                if (re.MaxAffected.HasValue)   found.Add("runningEmpty.maxAffected");
                if (re.Knight != null)
                {
                    if (re.Knight.ChancePercent.HasValue)
                        found.Add("runningEmpty.knight.chancePercent");
                    if (re.Knight.DurationDays.HasValue)
                        found.Add("runningEmpty.knight.durationDays");
                }
            }

            var od = f.OffDuty;
            if (od != null)
            {
                if (od.DurationDays.HasValue) found.Add("offDuty.durationDays");
                if (od.Knight != null && od.Knight.DurationDays.HasValue)
                    found.Add("offDuty.knight.durationDays");
            }

            return found;
        }

        private static void AddUnknown(Dictionary<string, JsonElement> unknown, string where,
                                       List<string> bad)
        {
            if (unknown == null) return;
            foreach (var kv in unknown)
                bad.Add($"\"{kv.Key}\" is not a recognised key in the {where}");
        }

        // The keys of a byPowerLevel dictionary are power levels rather than
        // member names, so only the anchors' own contents can be unrecognised.
        // The anchor is named by the key it was written under, which is the only
        // thing that finds it in the file.
        private static void AddUnknownLevels(Dictionary<string, LevelPoint> byLevel, string where,
                                             List<string> bad)
        {
            if (byLevel == null) return;
            foreach (var kv in byLevel)
                if (kv.Value != null)
                    AddUnknown(kv.Value.Unknown, $"{where} anchor \"{kv.Key}\"", bad);
        }

        private static bool Validate()
        {
            var re = o.RunningEmpty;
            var od = o.OffDuty;
            bool ok = true;

            if (re.TraitId == 0 || od.TraitId == 0)
            {
                Plugin.Log.LogError("Fatigue: traitId is 0 on one of the blocks. Both stages need "
                    + "a real TraitClass 6 id — 2009 Running Empty and 2014 Off-Duty are the "
                    + "shipped pair; 2007 Checked Out is the milder first stage.");
                ok = false;
            }
            if (re.TraitId == od.TraitId)
            {
                Plugin.Log.LogError($"Fatigue: both stages are trait {re.TraitId}. Escalation "
                    + "would be indistinguishable from the first grant, so the merc would never "
                    + "leave the first stage.");
                ok = false;
            }

            // WHAT A traitId IS AND IS NOT CHECKED FOR. It is checked for 0,
            // for the two stages being equal, for being negative, and for
            // landing in the range this project reserves for RowClone's
            // constructed rows. It is NOT checked against the content database:
            // this file has no TraitModel reader, and answering "does 2009
            // exist?" would mean asserting something about the game's data that
            // nothing here can verify. So "20009" typed for "2009" is caught
            // only when the typo lands in the reserved range; a typo onto any
            // other unused id still writes a dangling TraitTypeId that sits in
            // the save until it expires, and the grant lines in the log naming
            // an id nobody recognises are the only tell.
            //
            // The reserved-range half is deliberately blunt: RowClone keeps the
            // set of ids its clone rules DECLARE private, so this cannot ask
            // whether some rule creates the id. Everything in the range is
            // refused rather than warned about, because a dangling reference
            // this file would persist into the save is worse than a config that
            // has to move a deliberately cloned trait id out of the range.
            if (re.TraitId < 0 || od.TraitId < 0)
            {
                Plugin.Log.LogError($"Fatigue: a negative traitId (runningEmpty {re.TraitId}, "
                    + $"offDuty {od.TraitId}). Trait ids are positive.");
                ok = false;
            }
            if (re.TraitId >= CloneReservedFrom || od.TraitId >= CloneReservedFrom)
            {
                Plugin.Log.LogError($"Fatigue: a traitId (runningEmpty {re.TraitId}, offDuty "
                    + $"{od.TraitId}) is in the id range this project reserves for RowClone's "
                    + $"constructed rows ({CloneReservedFrom}+). The game ships no rows up there, "
                    + "so this is a typo, and every fatigued merc would carry a TraitTypeId that "
                    + "resolves to nothing until it expires. The feature is off rather than "
                    + "writing that into your save.");
                ok = false;
            }
            // THE FLAT RANGE CHECKS THAT USED TO SIT HERE ARE GONE, with the
            // settings they checked: runningEmpty.chancePercent 0-100,
            // runningEmpty.knight.chancePercent 0-100, durationDays >= 1 on both
            // blocks, minAffected >= 0, and maxAffected >= minAffected. Every
            // one of them still runs — on the anchors, in CheckLevels, which has
            // covered all four fields since 2.9.2, plus the PL 1-20 sweep below
            // for the pair that can only cross on a curve. Nothing was dropped;
            // the values simply moved.
            //
            // runningEmpty.byPowerLevel is now REQUIRED. There is no flat layer
            // behind it, so an absent or empty curve is a config that names no
            // chance, no duration and no counts at all — the feature would have
            // nothing to roll with. Refused rather than run on numbers nobody
            // chose, which is the same call Load makes about a misspelled key.
            if (!HasAnyCurve(re.ByPowerLevel))
            {
                Plugin.Log.LogError("Fatigue: runningEmpty.byPowerLevel is absent or empty, and "
                    + "since 2026-09-07 it is the only place the first stage's chance, duration, "
                    + "floor and ceiling live — the flat settings that used to back it up were "
                    + "removed. There is nothing to roll with, so the feature is OFF rather than "
                    + "running on built-in numbers nobody chose. Add at least one anchor; a "
                    + "single anchor at power level 1 applies at every level, which is what a "
                    + "flat value is now.");
                ok = false;
            }
            else
            {
                // A curve that exists but names neither field is the same hole
                // one level down, and it used to be impossible: chancePercent
                // and durationDays had initialisers and were range-checked, so
                // a config Validate accepted always had both. Caught here
                // rather than at the first mission completion, where it costs a
                // pair of errors and a roster nothing happened to. The Knight's
                // curve does not count — it is consulted first for HIM and
                // falls through to this one for everybody else, so a config
                // that names a chance only on his curve leaves every other merc
                // with none.
                if (!Names(re.ByPowerLevel, p => p.ChancePercent))
                {
                    Plugin.Log.LogError("Fatigue: no anchor of runningEmpty.byPowerLevel names "
                        + "chancePercent, so there is no chance to roll any merc against. Give "
                        + "at least one anchor a chancePercent.");
                    ok = false;
                }
                if (!Names(re.ByPowerLevel, p => p.DurationDays))
                {
                    Plugin.Log.LogError("Fatigue: no anchor of runningEmpty.byPowerLevel names "
                        + "durationDays, so a merc who failed the roll would be granted a trait "
                        + "with no expiry, which is PERMANENT. Give at least one anchor a "
                        + "durationDays.");
                    ok = false;
                }
            }

            var wr = o.WoundResist;
            if (wr.MinChancePercent < 0 || wr.MinChancePercent > 100)
            {
                Plugin.Log.LogError($"Fatigue: woundResist.minChancePercent is "
                    + $"{wr.MinChancePercent}; it is a percentage and has to be 0-100.");
                ok = false;
            }

            // The two Knight durationDays >= 1 checks that used to sit here went
            // with the settings they checked. CheckLevels applies the same rule
            // to every anchor of runningEmpty.knight.byPowerLevel and
            // offDuty.knight.byPowerLevel, so a zero-day Knight duration — a
            // PERMANENT trait, which is what the rule exists to stop — is still
            // rejected wherever it can now be written.
            //
            // offDuty.knight.chancePercent is NOT one of the removed settings.
            // It was never a real one: KnightBlock is shared with
            // runningEmpty.knight, so the key parses on the Off-Duty block too
            // and means nothing there. It keeps its own warning, which says why.
            if (od.Knight != null && od.Knight.ChancePercent.HasValue)
                Plugin.Log.LogWarning("Fatigue: offDuty.knight.chancePercent is set and means "
                    + "nothing. Escalation is not a roll — a merc who deploys carrying the first "
                    + "stage goes Off-Duty every time.");

            ok &= CheckLevels(re.ByPowerLevel, "runningEmpty.byPowerLevel", false);
            if (re.Knight != null)
                ok &= CheckLevels(re.Knight.ByPowerLevel, "runningEmpty.knight.byPowerLevel", false);

            // Off-Duty anchors carry durationDays and nothing else; the roll
            // belongs to the first stage.
            ok &= CheckLevels(od.ByPowerLevel, "offDuty.byPowerLevel", true);
            if (od.Knight != null)
                ok &= CheckLevels(od.Knight.ByPowerLevel, "offDuty.knight.byPowerLevel", true);

            // Every anchor can be legal on its own and the pair still cross at
            // some level in between — a floor anchored at PL 20 above a ceiling
            // anchored only at PL 1 is exactly the "ceiling undoes the floor"
            // case. This sweep is now the ONLY check for it: the flat
            // maxAffected-below-minAffected check went with the flat settings,
            // and every crossing a config can still express is a crossing on the
            // curve, which is what this walks.
            if (ok && HasAnyCurve(re.ByPowerLevel))
            {
                var crossed = new List<string>();
                for (long pl = 1; pl <= 20; pl++)
                {
                    var mx = MaxAffectedFor(pl);
                    if (mx.HasValue && mx.Value < MinAffectedFor(pl))
                        crossed.Add($"PL{pl} max {mx.Value} < min {MinAffectedFor(pl)}");
                }
                if (crossed.Count > 0)
                {
                    Plugin.Log.LogError("Fatigue: the byPowerLevel curve puts maxAffected below "
                        + "minAffected at " + string.Join(", ", crossed)
                        + ". The ceiling would undo the floor at those levels.");
                    ok = false;
                }
            }

            if (!ok) Plugin.Log.LogError("Fatigue: config rejected; nothing patched.");
            return ok;
        }

        private static bool HasAnyCurve(Dictionary<string, LevelPoint> byLevel)
        {
            return byLevel != null && byLevel.Count > 0;
        }

        /// <summary>Whether any anchor of a curve names one particular field.
        /// Curve() interpolates each field over only the anchors that name it,
        /// so a curve where none of them names a field has no value for it —
        /// which is the state Validate refuses for the two fields the first
        /// stage cannot happen without.</summary>
        private static bool Names(Dictionary<string, LevelPoint> byLevel,
                                  Func<LevelPoint, int?> pick)
        {
            if (byLevel == null) return false;
            foreach (var kv in byLevel)
                if (kv.Value != null && pick(kv.Value).HasValue) return true;
            return false;
        }

        // Every rule the flat blocks used to be checked against, checked on each
        // anchor. Before 2.9.2 this validated chancePercent alone, so a curve
        // could carry a durationDays of 0 — a PERMANENT trait — past a check
        // that rejected exactly that written flat. Since 2026-09-07 there is no
        // flat half left, so this is where those rules live, and it is the only
        // place a chance outside 0-100, a zero-day duration or a negative count
        // can now be caught.
        //
        // `durationOnly` marks the Off-Duty blocks, whose anchors interpolate
        // durationDays and nothing else. A chance or a count there is a
        // misunderstanding rather than a typo, so it is named and warned about
        // instead of being silently ignored, which is how offDuty.knight
        // .byPowerLevel got missed in the first place.
        private static bool CheckLevels(Dictionary<string, LevelPoint> byLevel, string where,
                                        bool durationOnly)
        {
            if (byLevel == null || byLevel.Count == 0) return true;
            bool ok = true;
            // Which key claimed each level, so two keys that parse to one level
            // can be named together below.
            var levelKeys = new Dictionary<int, string>();
            foreach (var kv in byLevel)
            {
                int lvl;
                if (!int.TryParse(kv.Key, NumberStyles.Integer, CultureInfo.InvariantCulture,
                                  out lvl))
                {
                    Plugin.Log.LogError($"Fatigue: {where} has a key \"{kv.Key}\" that is not a "
                        + "number. Keys are power levels.");
                    ok = false;
                    continue;
                }
                // "1" and "01" are two distinct dictionary keys that collapse to
                // one anchor level. Curve() keeps whichever the sort leaves at
                // that position and List.Sort is not stable, so which of the two
                // shapes the curve varies between runs. Caught here rather than
                // left to the run.
                string firstKey;
                if (levelKeys.TryGetValue(lvl, out firstKey))
                {
                    Plugin.Log.LogError($"Fatigue: {where} has both \"{firstKey}\" and "
                        + $"\"{kv.Key}\", which are the same power level {lvl}. Only one of them "
                        + "can anchor that level and which one wins is not stable between runs. "
                        + "Remove one.");
                    ok = false;
                }
                else levelKeys[lvl] = kv.Key;
                if (lvl < 1 || lvl > 20)
                    Plugin.Log.LogWarning($"Fatigue: {where} names power level {lvl}, outside "
                        + "1-20. It is still used as an anchor, but check it is deliberate.");
                var p = kv.Value;
                if (p == null) continue;

                if (p.ChancePercent.HasValue
                    && (p.ChancePercent.Value < 0 || p.ChancePercent.Value > 100))
                {
                    Plugin.Log.LogError($"Fatigue: {where}[{lvl}].chancePercent has to be 0-100.");
                    ok = false;
                }
                if (p.DurationDays.HasValue && p.DurationDays.Value <= 0)
                {
                    Plugin.Log.LogError($"Fatigue: {where}[{lvl}].durationDays is "
                        + $"{p.DurationDays.Value}; it has to be at least 1. A zero-turn "
                        + "ExpiresTurn is how the game marks a trait PERMANENT.");
                    ok = false;
                }
                if (p.MinAffected.HasValue && p.MinAffected.Value < 0)
                {
                    Plugin.Log.LogError($"Fatigue: {where}[{lvl}].minAffected cannot be negative.");
                    ok = false;
                }
                if (p.MaxAffected.HasValue && p.MaxAffected.Value < 0)
                {
                    Plugin.Log.LogError($"Fatigue: {where}[{lvl}].maxAffected cannot be negative. "
                        + "Zero is a real ceiling of zero; omit the key for no ceiling.");
                    ok = false;
                }
                if (p.MinAffected.HasValue && p.MaxAffected.HasValue
                    && p.MaxAffected.Value < p.MinAffected.Value)
                {
                    Plugin.Log.LogError($"Fatigue: {where}[{lvl}] has maxAffected "
                        + $"{p.MaxAffected.Value} below minAffected {p.MinAffected.Value}.");
                    ok = false;
                }

                if (durationOnly)
                {
                    var ignored = new List<string>();
                    if (p.ChancePercent.HasValue) ignored.Add("chancePercent");
                    if (p.MinAffected.HasValue) ignored.Add("minAffected");
                    if (p.MaxAffected.HasValue) ignored.Add("maxAffected");
                    if (ignored.Count > 0)
                        Plugin.Log.LogWarning($"Fatigue: {where}[{lvl}] sets "
                            + string.Join(", ", ignored) + ", which mean nothing on an Off-Duty "
                            + "anchor. Escalation is not a roll and has no floor or ceiling; only "
                            + "durationDays is read here.");
                }
            }
            return ok;
        }

        // ---- patching --------------------------------------------------------

        private static readonly Dictionary<string, Type> TypeCache =
            new Dictionary<string, Type>(StringComparer.Ordinal);

        private static Type ResolveType(string name)
        {
            Type t;
            if (TypeCache.TryGetValue(name, out t)) return t;
            // AccessTools.TypeByName walks every loaded assembly and makes
            // UnityEngine.CoreModule throw on the way past, so it is cached even
            // for the two names this file uses. docs/patching-rules.md.
            t = AccessTools.TypeByName(name);
            TypeCache[name] = t;
            return t;
        }

        // Every il2cpp method pointer this file has already patched, across all
        // of its Patch calls. Hoisted out of Patch: it used to be allocated
        // fresh inside each call, so it only ever compared the overloads of ONE
        // method name and the LoadGame/LoadGameSlot pair below — the case the
        // check is described as existing for — was never compared at all. Init
        // runs once, so one dictionary spans the whole patch pass.
        private static readonly Dictionary<IntPtr, string> patchClaims =
            new Dictionary<IntPtr, string>();

        // Two interop proxies resolving to one il2cpp method means two detours
        // on one address. This catches that case, including two proxies with
        // DIFFERENT names: the NativeMethodInfoPtr_<name>_* field read here is
        // each method's own, and what the two are compared on is the POINTER it
        // holds. It does NOT catch the harder one where the linker folded two
        // genuinely distinct bodies — nothing managed can, which is why
        // docs/patching-rules.md exists and why the only method patched here is
        // a substantial unique SQL insert.
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
                Plugin.Log.LogWarning($"Fatigue: could not resolve type '{typeName}'.");
                return 0;
            }

            var overloads = AccessTools.GetDeclaredMethods(t)
                .Where(m => m.Name == methodName && !m.IsAbstract).ToList();
            if (overloads.Count == 0)
            {
                Plugin.Log.LogWarning($"Fatigue: {t.Name} has no method '{methodName}'.");
                return 0;
            }

            var pf = new HarmonyMethod(AccessTools.Method(typeof(Fatigue), postfixName));
            int ok = 0;
            foreach (var m in overloads)
            {
                string owner;
                if (AlreadyClaimed(m, patchClaims, out owner))
                {
                    Plugin.Log.LogWarning($"Fatigue: NOT patching {t.Name}.{m.Name} — it is the "
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
                    Plugin.Log.LogWarning($"Fatigue: could not patch {t.Name}.{m.Name}: "
                                        + e.Message);
                }
            }
            return ok;
        }

        // ---- the hook --------------------------------------------------------

        // GameDb.InsertGameScore(GameScoreModel) -> Int64. __instance IS the
        // GameDb, and it is used here and dropped. Never stored: a captured
        // database instance that outlived its moment is what produced the Log7
        // mission hang, and 2.7.2's fix was "the live instance wins".
        //
        // One mission writes one type-19 row per deployed merc, then exactly one
        // type-16 with CharacterId 0 as terminator. Type 20
        // MissionCompleteByCharacterUnseen interleaves with the 19s and is
        // conditional on not being spotted, so it is ignored rather than counted.
        public static void AfterInsertGameScore(object __instance, object[] __args)
        {
            if (!active || reentrant) return;

            try
            {
                var score = __args != null && __args.Length > 0 ? __args[0] : null;
                if (score == null) return;

                long typeId;
                if (!TryNum(Get(score, "ScoreTypeId"), out typeId))
                {
                    // Read as 0 this row would fall through both phases anyway;
                    // the difference is that it is now said out loud, because
                    // every mission would do the same and nobody would ever be
                    // resolved.
                    NoteUnreadable("GameScoreModel", "ScoreTypeId");
                    return;
                }

                // Phase A, before anything else, so a resolve triggered below
                // always sees a complete roster.
                if (typeId == ScoreTypeCharacterOnMission)
                {
                    // THE SESSION-STATE FALLBACK, and it is a SECOND signal, not
                    // a replacement for the LoadGame hook. pendingRoster and
                    // pendingPowerLevel are session-global and used to be cleared
                    // only by a resolve, by the catch below, or by that hook —
                    // which is this file's one speculative patch, so where it
                    // patches nothing, mission A's roster leaked into mission B
                    // after a reload: mercs who never deployed on B rolled, and
                    // B resolved on A's power level.
                    //
                    // THE RULE, chosen from what this source can establish: one
                    // mission's type-19 rows all carry one GameTurn — Phase B
                    // reads the mission's turn off the type-16 terminator and
                    // stamps it on every row written for that mission — so a
                    // type-19 row whose turn differs from the turn already
                    // pending belongs to a different mission, and whatever is
                    // pending will never be terminated.
                    //
                    // WHAT IT DOES NOT COVER, explicitly: a reload that lands on
                    // the SAME turn as the pending mission is invisible to it —
                    // the turns match, the stale roster survives, and only the
                    // LoadGame hook can see that case. Nor does it hold if the
                    // game ever stamps one mission's type-19 rows with different
                    // turns; nothing in this source says it does, and the
                    // terminator carrying the mission's single turn is the
                    // reason to expect it does not. If it did, this would drop
                    // the earlier half of that mission's roster and say so in
                    // the log every time.
                    long rowTurn;
                    if (TryNum(Get(score, "GameTurn"), out rowTurn))
                    {
                        if (pendingRoster.Count > 0 && rowTurn != pendingTurn)
                            ForgetSession($"a mission row arrived at turn {rowTurn} while turn "
                                + $"{pendingTurn}'s roster was still pending");
                        pendingTurn = rowTurn;
                    }
                    else NoteUnreadable("GameScoreModel", "GameTurn");

                    long who;
                    if (!TryNum(Get(score, "CharacterId"), out who))
                    {
                        // Read as 0 this row would be dropped by the test below
                        // anyway; the difference is the log line, because a
                        // roster short one merc is a merc who never fatigues.
                        NoteUnreadable("GameScoreModel", "CharacterId");
                        return;
                    }
                    if (who != 0 && !pendingRoster.Contains(who)) pendingRoster.Add(who);

                    // Read the level on the first row of the mission, while the
                    // mission is certainly still active.
                    if (pendingPowerLevel == 0) pendingPowerLevel = ReadPowerLevel(__instance);
                    return;
                }

                // Phase B. The score row carries the turn, so no ReadGameData
                // call is needed and the turn stamped on the trait matches the
                // one stamped on the mission's own score rows.
                if (typeId == ScoreTypeMissionComplete)
                {
                    long turn;
                    if (!TryNum(Get(score, "GameTurn"), out turn))
                    {
                        // The turn is what CreatedTurn, ExpiresTurn and the
                        // double-fire key are all built out of. Read as 0 it
                        // would stamp this mission's rows with turn 0 and expire
                        // them a few turns after the epoch, so the mission is
                        // dropped instead of resolved on a fabricated turn.
                        NoteUnreadable("GameScoreModel", "GameTurn");
                        Plugin.Log.LogError("Fatigue: a mission-complete row arrived with an "
                            + "unreadable GameTurn. Every row this file writes is stamped with "
                            + "that turn, so nothing is written for this mission and the pending "
                            + "roster is dropped.");
                        pendingRoster.Clear();
                        pendingPowerLevel = 0;
                        pendingTurn = -1;
                        return;
                    }
                    Resolve(__instance, turn);
                }
            }
            catch (Exception e)
            {
                // A postfix that throws surfaces inside the game's own insert.
                // Losing a mission's fatigue is a much smaller problem than that.
                Plugin.Log.LogError($"Fatigue: the mission hook threw and was swallowed: {e}");
                pendingRoster.Clear();
                pendingTurn = -1;
            }
        }

        // Postfix on ViewModel_GameManagement.LoadGame / .LoadGameSlot. Takes no
        // arguments on purpose: it wants the fact that a load happened, nothing
        // out of it, and a signature that cannot go stale when the model types
        // move. The design doc's section 4.1 asks for exactly this.
        public static void AfterLoadGame()
        {
            if (!active) return;
            try { ForgetSession("a save was loaded"); }
            catch (Exception e)
            {
                Plugin.Log.LogError($"Fatigue: the load hook threw and was swallowed: {e}");
            }
        }

        // Everything this session remembers that a database rollback invalidates.
        // Two callers: the load hook, and Phase A's turn-discontinuity check.
        //
        // The log-once flags are deliberately NOT reset: they suppress a
        // repeated message rather than carry state, and clearing them would put
        // the same warning in the log after every load.
        private static void ForgetSession(string why)
        {
            int keys = resolved.Count;
            int stale = pendingRoster.Count;
            resolved.Clear();
            interrupted.Clear();
            pendingRoster.Clear();
            pendingPowerLevel = 0;
            pendingTurn = -1;
            safehouseRead = false;
            lookupCache.Clear();
            Plugin.Log.LogInfo($"Fatigue: {why} — dropped {keys} resolved mission key(s), a "
                + $"pending roster of {stale} merc(s), the pending power level and the cached "
                + "safehouse Wound Resist. Called from the load hook the design asks for and from "
                + "the turn-discontinuity check in Phase A; if you never see this line after "
                + "loading a save, the guard's own database check is what is keeping reloads "
                + "honest.");
        }

        // GameDb.ReadGameMissionActive() -> GameMissionModel, zero-arg. Read
        // inside the postfix and dropped; the model is never held.
        private static long ReadPowerLevel(object db)
        {
            bool outer = reentrant;
            reentrant = true;
            try
            {
                var mission = Call(db, "ReadGameMissionActive", Type.EmptyTypes, new object[0]);
                if (mission == null) return 0;
                // PowerLevel is the effective level, the one [PowerLevel] lifts
                // past the stock ceiling. PowerLevelUnscaled is the input to
                // that scaling and is the wrong column here.
                long pl;
                if (!TryNum(Get(mission, "PowerLevel"), out pl))
                {
                    // 0 is this method's "not read", and the caller warns once
                    // and takes every curve's lowest anchor for it. Naming the
                    // column as well is what separates a renamed column from a
                    // mission that simply was not readable.
                    NoteUnreadable("GameMissionModel", "PowerLevel");
                    return 0;
                }
                return pl;
            }
            catch (Exception e)
            {
                var inner = e.InnerException ?? e;
                Plugin.Log.LogWarning($"Fatigue: ReadGameMissionActive threw "
                    + $"{inner.GetType().Name}: {inner.Message}.");
                return 0;
            }
            finally { reentrant = outer; }
        }

        // ---- Phase B ---------------------------------------------------------

        private sealed class Candidate
        {
            public long Id;
            public string Name;
            public bool Knight;
            public int Roll;
            public int Threshold;
            public bool Gains;
            public bool Forced;         // pulled in by minAffected
            public bool Spared;         // pushed out by maxAffected
            public int BaseChance;      // before Wound Resist
            public Resist Resist;       // null when mitigation is off
            public bool Floored;        // resist would have pushed it below the floor

            // Distance from the threshold, regardless of side. The clamp works
            // on this, so a merc who barely passed is the first one the floor
            // reaches for and a merc who barely failed is the first one the
            // ceiling lets go.
            public int Distance { get { return Math.Abs(Roll - Threshold); } }
        }

        private static void Resolve(object db, long turn)
        {
            var roster = new List<long>(pendingRoster);
            pendingRoster.Clear();
            long powerLevel = pendingPowerLevel;
            pendingPowerLevel = 0;
            pendingTurn = -1;              // nothing is pending once it is taken

            // Phase A may have missed it if the type-19 rows arrived before the
            // mission was readable. One more try, then the lowest anchor.
            if (powerLevel == 0) powerLevel = ReadPowerLevel(db);
            if (powerLevel == 0 && !warnedNoPowerLevel)
            {
                warnedNoPowerLevel = true;
                // REWRITTEN 2026-09-07 with the ruling it describes. It used to
                // say "the byPowerLevel curves do not apply and the flat values
                // are used", which was true while there were flat values to fall
                // back to. There are none now, and Curve() clamps a 0 to the
                // lowest anchor instead, so the curves DO apply — at their low
                // end. The warning stays because a mission whose level cannot be
                // read is still worth knowing about: every such mission is
                // priced as the cheapest one on the curve.
                Plugin.Log.LogWarning("Fatigue: could not read the mission's PowerLevel. The "
                    + "byPowerLevel curves still apply and every value is taken from the LOWEST "
                    + "anchor each curve names, as though this were the lowest level configured. "
                    + "Said once.");
            }

            if (roster.Count == 0)
            {
                Plugin.Log.LogWarning($"Fatigue: mission completed at turn {turn} with no type-19 "
                    + "rows collected. Nobody was resolved. If this repeats, the roster for this "
                    + "mission type comes from somewhere other than the score rows.");
                return;
            }

            // SOLO MISSIONS ARE EXEMPT. David's ruling, 2026-09-10: a mission run
            // by one character does not run the fatigue mechanic at all. No
            // roll, no escalation to Off-Duty, nothing written, so a merc who
            // goes out alone while Running Empty keeps the first stage and is
            // not locked out. "One character" is one distinct CharacterId among
            // the mission's type-19 rows, which is the only roster this hook
            // has. Checked before the double-fire guard because nothing is
            // written for it to guard.
            if (roster.Count == 1)
            {
                Plugin.Log.LogInfo($"Fatigue: mission complete at turn {turn} with one merc "
                    + $"deployed (character {roster[0]}). Solo missions are exempt: no roll, no "
                    + "escalation, nothing written.");
                return;
            }

            // Section 4.1. Re-entering the victory screen must not resolve the
            // same mission twice: the second pass would see the first stage the
            // first pass granted and escalate it straight to Off-Duty.
            var key = turn + ":" + string.Join(",", roster.OrderBy(x => x));
            if (resolved.Contains(key))
            {
                // Session memory says this mission was resolved. A database
                // rollback does not touch session memory, so before trusting it
                // ask the database whether that resolution's rows are still
                // there. Blocking on a stale key is the failure this check
                // exists for: a reload to before the mission, replayed to the
                // same end turn with the same roster, used to write NOTHING —
                // the reload ERASED the fatigue instead of reproducing it,
                // which is the exact inverse of what deterministic rolls are
                // for.
                if (AlreadyWritten(db, roster, turn))
                {
                    if (interrupted.Contains(key))
                        Plugin.Log.LogWarning($"Fatigue: the earlier resolution of turn {turn} "
                            + "with this roster never reached the end of its write loop, so some "
                            + "of these mercs may never have been rolled for at all. Nothing is "
                            + "written now either: rows from that pass are in the database and "
                            + "this file cannot tell which mercs are missing theirs.");
                    Plugin.Log.LogWarning($"Fatigue: turn {turn} with this roster has already "
                        + "been resolved and its rows are still in the database. Nothing written. "
                        + "This is the double-grant guard; a second type-16 row for one mission "
                        + "is itself worth knowing about.");
                    return;
                }

                resolved.Remove(key);
                interrupted.Remove(key);
                Plugin.Log.LogInfo($"Fatigue: turn {turn} with this roster was resolved earlier "
                    + "this session, but none of those rows are in the database any more — the "
                    + "save was loaded back to before the mission. Resolving it again. With "
                    + "deterministic rolls the outcome is the one you saw the first time.");
            }

            // MARKED BEFORE ANY ROW IS WRITTEN, deliberately. A resolution that
            // throws half way through leaves the key set, so a re-fire is blocked
            // by session memory and cannot write a second row for the mercs the
            // first pass already wrote — the bias is against double-writing. What
            // that used to cost is that a partial resolution was indistinguishable
            // from a complete one, so the key is ALSO recorded as interrupted here
            // and removed only where the write loop reaches its end; a guard hit
            // on an interrupted key says so above instead of reporting a clean
            // double-fire.
            resolved.Add(key);
            interrupted.Add(key);

            // Once per mission rather than once per session, so a Triage Clinic
            // built or upgraded between missions counts and another save slot
            // does not inherit this one's number.
            safehouseRead = false;
            lookupCache.Clear();

            var re = o.RunningEmpty;
            var od = o.OffDuty;

            // `unconfigured` counts mercs the curves had no number for. It is
            // deliberately not folded into `passed` or `skipped`: both of those
            // are statements about the merc — they rolled clear, or they were
            // already Off-Duty — and neither is true of a merc nothing could be
            // resolved for. NoteMissingCurve says which key is missing; this
            // says how many mercs it cost on this mission.
            int escalated = 0, granted = 0, passed = 0, skipped = 0, failed = 0, unconfigured = 0;
            var pool = new List<Candidate>();

            if (o.LogGrants)
            {
                var headChance = ChanceFor(false, powerLevel);
                var headMax = MaxAffectedFor(powerLevel);
                Plugin.Log.LogInfo($"Fatigue: mission complete at turn {turn}, power level "
                    + (powerLevel > 0 ? powerLevel.ToString()
                                      : "unreadable, so the lowest anchor of each curve")
                    + $", roster {string.Join(", ", roster)}. Chance "
                    + (headChance.HasValue ? headChance.Value.ToString() + "%" : "UNSET")
                    + $", min {MinAffectedFor(powerLevel)}, max "
                    + (headMax.HasValue ? headMax.Value.ToString() : "none") + ".");
            }

            // Saved and restored rather than set true and cleared to false, the
            // way ReadPowerLevel and AlreadyWritten do it. Resolve has one caller
            // today so nothing reaches it already re-entrant; a second caller is
            // all it would take for the plain `false` to clear a flag it did not
            // set, and re-enter the game's own insert through our postfix.
            bool outerReentrant = reentrant;
            reentrant = true;
            try
            {
                // Steps 1-3 of section 4: read, escalate, then build the pool
                // out of whoever is left. Because the read happens before any
                // write, "went out while Running Empty" needs no CreatedTurn
                // arithmetic and no deploy-time hook.
                foreach (var who in roster)
                {
                    // A reader that RETURNS NULL costs exactly what a reader
                    // that throws costs: `ch` is null, IsKnight reads 0 and
                    // DisplayName reads "". Only the throw used to be reported,
                    // so a null return was completely silent and the Knight
                    // rolled on the general odds with nothing in the log. Both
                    // arrive here as `chFailed` and both trip the same
                    // once-per-session warning.
                    object ch = null;
                    string chFailed = null;
                    try
                    {
                        ch = Call(db, "ReadGameCharacter", new[] { typeof(long) },
                                  new object[] { who });
                        if (ch == null) chFailed = "returned null";
                    }
                    catch (Exception e)
                    {
                        var inner = e.InnerException ?? e;
                        chFailed = $"threw {inner.GetType().Name}: {inner.Message}";
                    }
                    if (chFailed != null && !warnedNoCharacterReader)
                    {
                        // Losing this reader is not fatal — the roll still
                        // happens — but every merc then reads IsKnight 0 and
                        // DisplayName "", so the Knight quietly rolls on the
                        // general odds and serves the general duration, and a
                        // blank name in the log is the only tell.
                        warnedNoCharacterReader = true;
                        Plugin.Log.LogWarning($"Fatigue: ReadGameCharacter({who}) {chFailed}. "
                            + "Names will be blank and NOBODY will be recognised as the Knight, "
                            + "so his own odds and duration stop applying. Said once.");
                    }
                    var name = Str(Get(ch, "DisplayName"));

                    // IsKnight picks which block's odds and duration apply, so
                    // an unreadable column is named rather than quietly read as
                    // "not the Knight". It gates no write, so the merc still
                    // rolls — on the general odds, as they would have anyway.
                    long isKnight = 0;
                    if (ch != null && !TryNum(Get(ch, "IsKnight"), out isKnight))
                    {
                        NoteUnreadable("GameCharacterModel", "IsKnight");
                        isKnight = 0;
                    }
                    bool knight = isKnight != 0;

                    object rows;
                    try
                    {
                        rows = Call(db, "ReadGameCharacterTraitsByCharacter",
                                    new[] { typeof(long) }, new object[] { who });
                    }
                    catch (Exception e)
                    {
                        var inner = e.InnerException ?? e;
                        Plugin.Log.LogError($"Fatigue: reading traits for {who} threw "
                            + $"{inner.GetType().Name}: {inner.Message}. Skipped.");
                        failed++;
                        continue;
                    }

                    // A trait list that could not be read all the way through is
                    // "cannot look", not "carries nothing". Granting on it hands
                    // the merc a second first-stage row every mission, and the
                    // duplicates are then invisible to the escalation scan for
                    // the same reason.
                    bool traitsComplete;
                    var traitRows = Rows(rows, out traitsComplete);
                    if (!traitsComplete)
                    {
                        Plugin.Log.LogWarning($"Fatigue: the trait list for {who} {name} could "
                            + "not be read all the way through, so this mission cannot tell what "
                            + "fatigue they already carry. Skipped rather than granted.");
                        failed++;
                        continue;
                    }

                    // TraitTypeId decides escalation and Id is what Revoke
                    // deletes. Num() turns an unreadable column into 0 on every
                    // row, which reads as "this merc carries nothing" forever:
                    // the mod would never escalate anyone, never see the row it
                    // granted last mission, and grant another one every mission.
                    // So an unreadable column skips the merc instead.
                    var firstStageRowIds = new List<long>();
                    bool hasOffDuty = false, unreadableTrait = false;
                    foreach (var t in traitRows)
                    {
                        long tt;
                        if (!TryNum(Get(t, "TraitTypeId"), out tt))
                        {
                            NoteUnreadable("GameCharacterTraitModel", "TraitTypeId");
                            unreadableTrait = true;
                            break;
                        }
                        if (tt == re.TraitId)
                        {
                            long rowId;
                            // A 0 here is either the same reflection miss or a
                            // row this code cannot address; deleting row 0 is
                            // not something to try either way.
                            if (!TryNum(Get(t, "Id"), out rowId) || rowId == 0)
                            {
                                NoteUnreadable("GameCharacterTraitModel", "Id");
                                unreadableTrait = true;
                                break;
                            }
                            firstStageRowIds.Add(rowId);
                        }
                        else if (tt == od.TraitId) hasOffDuty = true;
                    }
                    if (unreadableTrait)
                    {
                        Plugin.Log.LogWarning($"Fatigue: a trait row for {who} {name} has an "
                            + "unreadable or zero TraitTypeId/Id, so escalation cannot be decided "
                            + "and a grant could duplicate a row already there. Skipped.");
                        failed++;
                        continue;
                    }

                    if (hasOffDuty)
                    {
                        // Already locked out and deployed anyway, which the game
                        // allows for a story-required mission. Nothing to add.
                        if (o.LogGrants)
                            Plugin.Log.LogInfo($"Fatigue:   {who} {name}: already Off-Duty, "
                                             + "skipped.");
                        skipped++;
                        continue;
                    }

                    if (firstStageRowIds.Count > 0)
                    {
                        var offDutyDays = OffDutyDaysFor(knight, powerLevel);
                        if (!offDutyDays.HasValue)
                        {
                            // No Off-Duty duration anywhere in the curves. The
                            // merc KEEPS the first stage — the same call the
                            // failed-insert branch below makes, and for the same
                            // reason: the alternative is a row with a zero
                            // ExpiresTurn, which the game reads as PERMANENT and
                            // which would put this merc off the roster for the
                            // rest of the save. NoteMissingCurve has already
                            // named the key, once; this names the merc it cost.
                            Plugin.Log.LogWarning($"Fatigue: {who} {name} deployed while carrying "
                                + $"{re.TraitId} and is NOT escalated: offDuty.byPowerLevel names "
                                + "no durationDays at this power level, so there is no length to "
                                + "write. They keep the first stage and will escalate again next "
                                + "mission, once the curve carries a duration.");
                            unconfigured++;
                            continue;
                        }
                        int days = offDutyDays.Value;

                        // This file grants one first-stage row at a time, so more
                        // than one on a merc is itself evidence of a defect
                        // upstream and is named. All of them are revoked below;
                        // keeping only the LAST match, as this used to, left the
                        // others behind and the merc escalated again next mission
                        // — the loop the revoke exists to prevent.
                        if (firstStageRowIds.Count > 1)
                            Plugin.Log.LogWarning($"Fatigue: {who} {name} carries "
                                + $"{firstStageRowIds.Count} rows of trait {re.TraitId} (rows "
                                + string.Join(", ", firstStageRowIds) + "). One is what this file "
                                + "grants, so the rest came from somewhere else and are worth "
                                + "reporting. All of them go with the escalation.");

                        if (o.LogGrants)
                            Plugin.Log.LogInfo($"Fatigue:   {who} {name}{(knight ? " [KNIGHT]" : "")}"
                                + $": deployed while carrying {re.TraitId} -> Off-Duty for "
                                + $"{days} day(s), no roll.");

                        if (Apply(db, who, od.TraitId, turn, days, "escalate"))
                        {
                            escalated++;

                            // Without this the merc comes back off Off-Duty
                            // still carrying the first stage, and the next
                            // mission locks them again — a loop until the first
                            // stage runs out. EVERY first-stage row goes, not
                            // just the last one the scan found.
                            if (od.ClearsRunningEmpty)
                                foreach (var rowId in firstStageRowIds) Revoke(db, who, rowId);
                        }
                        else
                        {
                            // The escalation did NOT go in, so the first stage
                            // is all the fatigue this merc has. Deleting it here
                            // would leave them carrying nothing at all and the
                            // mission would have REMOVED fatigue instead of
                            // escalating it. Keep the rows — all of them — and
                            // say so.
                            failed++;
                            Plugin.Log.LogWarning($"Fatigue: {who} {name} keeps trait "
                                + $"{re.TraitId} (row(s) " + string.Join(", ", firstStageRowIds)
                                + ") because the Off-Duty insert failed. They escalate again next "
                                + "mission.");
                        }
                        continue;
                    }

                    var configuredChance = ChanceFor(knight, powerLevel);
                    if (!configuredChance.HasValue)
                    {
                        // THE ROLL DOES NOT HAPPEN. There is no chance to roll
                        // against and no flat value left to borrow one from, and
                        // rolling against a number nobody configured is the
                        // silent-default failure this file refuses everywhere
                        // else. The merc is left alone and counted as
                        // unconfigured, not as clear: they were never rolled
                        // for. NoteMissingCurve named the key once already.
                        if (o.LogGrants)
                            Plugin.Log.LogInfo($"Fatigue:   {who} {name}"
                                + (knight ? " [KNIGHT]" : "")
                                + ": not rolled — runningEmpty.byPowerLevel names no "
                                + "chancePercent at this power level.");
                        unconfigured++;
                        continue;
                    }
                    int chance = configuredChance.Value;
                    var c = new Candidate
                    {
                        Id = who,
                        Name = name,
                        Knight = knight,
                        BaseChance = chance,
                        Threshold = chance
                    };

                    if (o.WoundResist.Enabled)
                    {
                        // The trait rows are already in hand from the read above,
                        // so this costs three extra reads per merc, not four.
                        c.Resist = ResistFor(db, who, rows);
                        bool floored;
                        c.Threshold = ThresholdFor(chance, c.Resist.Total, out floored);
                        c.Floored = floored;
                    }
                    pool.Add(c);
                }

                // Steps 4 and 5: roll, then clamp the count without disturbing
                // who the odds picked.
                foreach (var c in pool)
                {
                    c.Roll = o.DeterministicRolls ? StableRoll(turn, c.Id) : rng.Next(100);
                    c.Gains = c.Roll < c.Threshold;
                }
                Clamp(pool, MinAffectedFor(powerLevel), MaxAffectedFor(powerLevel));

                // Step 6.
                foreach (var c in pool)
                {
                    // Only asked for where it is needed. A merc who rolled clear
                    // needs no duration, so a curve with no durationDays does not
                    // turn their clear roll into a report about the config.
                    int? grantDays = c.Gains
                                   ? RunningEmptyDaysFor(c.Knight, powerLevel)
                                   : (int?)null;

                    if (o.LogGrants)
                        Plugin.Log.LogInfo($"Fatigue:   {c.Id} {c.Name}{(c.Knight ? " [KNIGHT]" : "")}"
                            + $": rolled {c.Roll} vs {c.Threshold}{Explain(c)} -> "
                            + (!c.Gains ? "clear"
                               : grantDays.HasValue
                                 ? "trait " + re.TraitId + " for " + grantDays.Value + " day(s)"
                                 : "NOT GRANTED, no durationDays on the curve")
                            + (c.Forced ? "  (pulled in by minAffected)" : "")
                            + (c.Spared ? "  (spared by maxAffected)" : ""));

                    if (!c.Gains) { passed++; continue; }
                    if (!grantDays.HasValue)
                    {
                        // Rolled a hit, and the trait is still not written: a
                        // grant with no duration would carry a zero ExpiresTurn,
                        // which is how the game marks a trait PERMANENT. Nothing
                        // is written and it is counted apart from both a clear
                        // roll and a failed write, because it is neither.
                        Plugin.Log.LogWarning($"Fatigue: {c.Id} {c.Name} rolled a hit and takes "
                            + "NOTHING: runningEmpty.byPowerLevel names no durationDays at this "
                            + "power level, and a grant with no duration would be a PERMANENT "
                            + "trait.");
                        unconfigured++;
                        continue;
                    }
                    if (Apply(db, c.Id, re.TraitId, turn, grantDays.Value, "roll")) granted++;
                    else failed++;
                }

                // The write loop reached its end, so this key is a complete
                // resolution rather than an interrupted one.
                interrupted.Remove(key);
            }
            catch (Exception e)
            {
                Plugin.Log.LogError($"Fatigue: resolving turn {turn} threw and was swallowed: {e}");
            }
            finally { reentrant = outerReentrant; }

            var line = $"Fatigue: mission at turn {turn}, {roster.Count} merc(s) — {granted} "
                     + $"fatigued, {escalated} sent Off-Duty, {passed} clear, {skipped} already "
                     + $"Off-Duty";
            // Reported apart from `failed`. A write that failed and a merc the
            // config had no number for are different findings and do not share a
            // log level either: the second is a config that needs an anchor, and
            // saying "FAILED TO WRITE" about it would send the reader looking at
            // the database.
            if (unconfigured > 0)
                line += $", {unconfigured} not resolved for want of a configured value";
            if (failed > 0) Plugin.Log.LogError(line + $", {failed} FAILED TO WRITE.");
            else if (unconfigured > 0) Plugin.Log.LogWarning(line + ".");
            else if (o.LogGrants || granted + escalated > 0) Plugin.Log.LogInfo(line + ".");
        }

        // Does the database still carry the rows a previous resolution of this
        // exact mission wrote? Every row Apply writes is stamped
        // CreatedTurn = the mission's turn, so a first-stage or Off-Duty row at
        // that turn on any roster merc is that resolution's own evidence, and a
        // save loaded back to before the mission rolls it away with everything
        // else. That is the whole difference between a genuine second type-16
        // row and a replay, and it is the only one the database can see.
        //
        // A mission where nobody was granted anything leaves no evidence, so a
        // genuine double-fire on one resolves twice. With deterministicRolls
        // that reproduces the same all-clear outcome and costs nothing; with
        // rolls unseeded it can differ, which is one more reason unseeded is
        // marked testing-only.
        //
        // Only ever called on a guard hit, so its cost is one read per merc on
        // a path that should almost never run.
        private static bool AlreadyWritten(object db, List<long> roster, long turn)
        {
            bool outer = reentrant;
            reentrant = true;
            try
            {
                foreach (var who in roster)
                {
                    object rows;
                    try
                    {
                        rows = Call(db, "ReadGameCharacterTraitsByCharacter",
                                    new[] { typeof(long) }, new object[] { who });
                    }
                    catch (Exception e)
                    {
                        // Cannot tell. Keep the guard's old behaviour, which
                        // costs a mission's fatigue rather than risking a second
                        // escalation onto a merc who is already Off-Duty.
                        var inner = e.InnerException ?? e;
                        Plugin.Log.LogWarning($"Fatigue: checking whether turn {turn} was already "
                            + $"written threw {inner.GetType().Name}: {inner.Message}. Treating "
                            + "the mission as already resolved.");
                        return true;
                    }

                    // A partial list read cannot say a row is ABSENT, and this
                    // guard's whole question is whether the rows are still there.
                    // Same call as the catch above: cannot tell means treat the
                    // mission as already resolved, which costs a mission's
                    // fatigue rather than risking a second escalation onto a merc
                    // who is already Off-Duty.
                    bool complete;
                    var traitRows = Rows(rows, out complete);
                    if (!complete)
                    {
                        Plugin.Log.LogWarning($"Fatigue: the trait list for {who} could not be "
                            + $"read all the way through while checking whether turn {turn} was "
                            + "already written. Treating the mission as already resolved.");
                        return true;
                    }

                    foreach (var t in traitRows)
                    {
                        // Num() would read a renamed column as 0 on every row, so
                        // no row would ever match and the guard would degrade to
                        // "nothing was written" — which sends the resolution
                        // through a second time.
                        long tt;
                        if (!TryNum(Get(t, "TraitTypeId"), out tt))
                        {
                            NoteUnreadable("GameCharacterTraitModel", "TraitTypeId");
                            Plugin.Log.LogWarning($"Fatigue: a trait row for {who} has an "
                                + $"unreadable TraitTypeId, so whether turn {turn} was already "
                                + "written cannot be told. Treating it as already resolved.");
                            return true;
                        }
                        if (tt != o.RunningEmpty.TraitId && tt != o.OffDuty.TraitId) continue;
                        long created;
                        if (!TryNum(Get(t, "CreatedTurn"), out created))
                        {
                            NoteUnreadable("GameCharacterTraitModel", "CreatedTurn");
                            Plugin.Log.LogWarning($"Fatigue: a trait row for {who} has an "
                                + $"unreadable CreatedTurn, so whether turn {turn} was already "
                                + "written cannot be told. Treating it as already resolved.");
                            return true;
                        }
                        if (created == turn) return true;
                    }
                }
                return false;
            }
            finally { reentrant = outer; }
        }

        // "25 base - 30 resist, floored at 5" — the whole arithmetic behind one
        // threshold, on the line that used it. Without this the log shows a
        // number nobody can check.
        private static string Explain(Candidate c)
        {
            if (c.Resist == null) return "";

            var r = c.Resist;
            var parts = new List<string>();
            if (r.Safehouse != 0) parts.Add($"safehouse {r.Safehouse:+#;-#;0}");
            if (r.Permanent != 0) parts.Add($"permanent {r.Permanent:+#;-#;0}");
            if (r.Timed != 0) parts.Add($"timed {r.Timed:+#;-#;0}");
            if (r.Gear != 0) parts.Add($"gear {r.Gear:+#;-#;0}");
            if (r.Overlapped != 0) parts.Add($"{r.Overlapped:+#;-#;0} counted once");

            // "no resist" used to be the whole bracket whenever the total was 0,
            // and Run63 showed that is not enough: it reads the same for a merc
            // with no WoundRes anywhere and for one whose rows were never seen.
            // The read summary is what tells those apart.
            return "  [" + (r.Total == 0 ? $"{c.BaseChance} base, no resist"
                                        : $"{c.BaseChance} base - {r.Total:+#;-#;0} resist")
                 + (parts.Count > 0 ? " (" + string.Join(", ", parts) + ")" : "")
                 + (c.Floored ? $", floored at {o.WoundResist.MinChancePercent}" : "")
                 + (r.Sources.Count > 0 ? "; read " + ReadSummary(r) : "") + "]";
        }

        // "trait 6, effect 0, implant 3 (2 with WoundRes, 3 via DataDb), job 14"
        private static string ReadSummary(Resist r)
        {
            var bits = new List<string>();
            foreach (var st in r.Sources)
            {
                if (st.Unreadable && st.Rows == 0) { bits.Add(st.Name + " UNREADABLE"); continue; }
                var notes = new List<string>();
                if (st.Carrying > 0) notes.Add($"{st.Carrying} with WoundRes");
                if (st.LookedUp > 0) notes.Add($"{st.LookedUp} via DataDb");
                if (st.NoEffect > 0) notes.Add($"{st.NoEffect} name no effect");
                if (st.Unresolved > 0) notes.Add($"{st.Unresolved} UNRESOLVED");
                if (st.Unreadable) notes.Add("PARTIAL");
                bits.Add($"{st.Name} {st.Rows}" + (notes.Count > 0 ? " (" + string.Join(", ", notes) + ")" : ""));
            }
            return string.Join(", ", bits);
        }

        // The floor and the ceiling move the COUNT; the rolls decide WHO. A merc
        // is pulled in or let go by how close their roll landed to their own
        // threshold, so the odds still shape the outcome and the counts only
        // bound it. Ties break on character id so a reload reproduces the same
        // set, which is the whole point of deterministicRolls.
        //
        // The Cyber Knight is in this pool like anyone else — David, 2026-08-30.
        private static void Clamp(List<Candidate> pool, int minAffected, int? maxAffected)
        {
            if (pool.Count == 0) return;

            int failures = pool.Count(c => c.Gains);

            // minAffected is capped at the pool size, so a mission where
            // everyone already carries the trait cannot force a grant onto
            // nobody.
            int floor = Math.Min(minAffected, pool.Count);
            if (failures < floor)
            {
                foreach (var c in pool.Where(c => !c.Gains)
                                      .OrderBy(c => c.Distance).ThenBy(c => c.Id)
                                      .Take(floor - failures))
                { c.Gains = true; c.Forced = true; }
                failures = floor;
            }

            if (maxAffected.HasValue && failures > maxAffected.Value)
            {
                foreach (var c in pool.Where(c => c.Gains)
                                      .OrderBy(c => c.Distance).ThenBy(c => c.Id)
                                      .Take(failures - maxAffected.Value))
                { c.Gains = false; c.Spared = true; }
            }
        }

        // ---- the power-level curve -------------------------------------------

        // Anchors interpolate. Two anchors at levels 1 and 20 describe the whole
        // range; twenty anchors describe it exactly; one anchor is a flat value
        // that happens to be written as a curve. Below the lowest anchor and
        // above the highest, the nearest anchor's value holds rather than the
        // line continuing — a curve is a statement about the levels it names,
        // not an extrapolation past them.
        //
        // `pick` chooses which field of the anchor this call is interpolating,
        // so each field walks only the anchors that actually name it.
        //
        // AN UNREADABLE POWER LEVEL TAKES THE LOWEST ANCHOR. David's ruling,
        // 2026-09-07. This used to return null for `powerLevel <= 0`, which sent
        // the caller to the flat value; with the flat values gone that would
        // have been a resolver with no answer on the one path that is nobody's
        // fault. 0 is below every anchor a sane config names, so it falls into
        // the `powerLevel <= pts[0].Key` clamp two lines down and comes back
        // with the curve's lowest value — which is exactly what the flat value
        // it replaces would have produced. Resolve still warns once that the
        // level could not be read. The only remaining null is a curve that names
        // no value for this field at all.
        private static int? Curve(Dictionary<string, LevelPoint> byLevel,
                                  Func<LevelPoint, int?> pick, long powerLevel)
        {
            if (byLevel == null || byLevel.Count == 0) return null;

            var pts = new List<KeyValuePair<int, int>>();
            foreach (var kv in byLevel)
            {
                int lvl;
                if (!int.TryParse(kv.Key, NumberStyles.Integer, CultureInfo.InvariantCulture, out lvl))
                    continue;
                if (kv.Value == null) continue;
                var v = pick(kv.Value);
                if (v.HasValue) pts.Add(new KeyValuePair<int, int>(lvl, v.Value));
            }
            if (pts.Count == 0) return null;
            pts.Sort((a, b) => a.Key.CompareTo(b.Key));

            if (powerLevel <= pts[0].Key) return pts[0].Value;
            if (powerLevel >= pts[pts.Count - 1].Key) return pts[pts.Count - 1].Value;

            for (int i = 1; i < pts.Count; i++)
            {
                if (pts[i].Key < powerLevel) continue;
                var lo = pts[i - 1];
                var hi = pts[i];
                if (hi.Key == lo.Key) return hi.Value;
                double t = (double)(powerLevel - lo.Key) / (hi.Key - lo.Key);
                // Away from zero, so a curve through 10 and 25 gives 18 at the
                // midpoint rather than banker's-rounding to 18 in one direction
                // and 17 in the other.
                return (int)Math.Round(lo.Value + t * (hi.Value - lo.Value),
                                       MidpointRounding.AwayFromZero);
            }
            return pts[pts.Count - 1].Value;
        }

        // ---- the four tunables, resolved for one merc at one power level -----
        //
        // Knight curve beats general curve, and that is the whole chain now: the
        // flat settings each of these used to fall back to were removed on
        // 2026-09-07 (David's ruling). Two consequences worth stating plainly,
        // because both used to be impossible:
        //
        // 1. An unreadable PowerLevel is no longer a fallback path. Curve()
        //    clamps a 0 to the lowest anchor, so these return a real configured
        //    number for it, the same one a PL 1 mission gets.
        // 2. A curve that names NO value for the field being asked for is a
        //    config with no value, and these say so instead of inventing one.
        //    WHAT THEY DO ABOUT IT:
        //
        //    * ChanceFor, RunningEmptyDaysFor and OffDutyDaysFor return null.
        //      There is no safe number to substitute — a chance nobody chose is
        //      the silent-default failure the Unknown buckets exist to prevent,
        //      and a duration of 0 is how the game marks a trait PERMANENT, so a
        //      0 here would lock a merc off the roster for good. The CALLER does
        //      not roll and does not write, and logs which key is missing. A
        //      merc who cannot be rolled for is counted separately in the
        //      mission summary rather than folded into "clear".
        //    * MinAffectedFor returns NoMinAffected (0) and says so once. A
        //      missing floor has a safe, stateable meaning — no floor — and 0 is
        //      what the removed setting's own default was, so this is the one
        //      case where a named constant is honest rather than a guess.
        //    * MaxAffectedFor returns null, which is not a missing value: null
        //      has always meant "no ceiling" here and still does. Unchanged.
        //
        // In a config Validate accepted, only case 2 with a PARTIAL curve can
        // reach these — runningEmpty.byPowerLevel is required, but a curve whose
        // anchors name chancePercent and nothing else is legal, and offDuty
        // .byPowerLevel is not required at all, so OffDutyDaysFor is the one
        // most likely to come back empty.

        // 0 is a floor of zero, which is no floor: the clamp reaches for nobody.
        // Named so the log can say what it used rather than printing a bare 0.
        private const int NoMinAffected = 0;

        // Which missing curve values have already been reported this session, so
        // a config with no durationDays anywhere costs one line rather than one
        // per merc per mission. Same rule as unreadableWarned.
        private static readonly HashSet<string> missingCurveWarned =
            new HashSet<string>(StringComparer.Ordinal);

        // `blocking` is false only for minAffected, whose absence has a legal
        // meaning — no floor — and so is a WARNING rather than an ERROR. The
        // other three cost a roll or a write, and are errors.
        private static void NoteMissingCurve(string what, string consequence,
                                             bool blocking = true)
        {
            if (!missingCurveWarned.Add(what)) return;
            var msg = $"Fatigue: no anchor of {what} names a value, and there is no flat setting "
                + "behind it any more — those were removed on 2026-09-07. " + consequence
                + " Said once. Add the field to at least one anchor; an anchor holds at every "
                + "level below the one it names, so a single one at power level 1 covers the "
                + "whole range.";
            if (blocking) Plugin.Log.LogError(msg);
            else Plugin.Log.LogWarning(msg);
        }

        // Null means the curves name no chance for this merc. The caller does not
        // roll them.
        private static int? ChanceFor(bool knight, long pl)
        {
            var re = o.RunningEmpty;
            if (knight && re.Knight != null)
            {
                var k = Curve(re.Knight.ByPowerLevel, p => p.ChancePercent, pl);
                if (k.HasValue) return k.Value;
            }
            var g = Curve(re.ByPowerLevel, p => p.ChancePercent, pl);
            if (g.HasValue) return g.Value;
            NoteMissingCurve("runningEmpty.byPowerLevel chancePercent",
                "No merc can be rolled for, so none of them takes the first stage from any "
                + "mission; escalation of a merc who already carries it still happens.");
            return null;
        }

        // Null means the curves name no first-stage duration for this merc. The
        // caller does not write the trait: a 0-day grant is a PERMANENT trait,
        // which is the one outcome worse than no grant at all.
        private static int? RunningEmptyDaysFor(bool knight, long pl)
        {
            var re = o.RunningEmpty;
            if (knight && re.Knight != null)
            {
                var k = Curve(re.Knight.ByPowerLevel, p => p.DurationDays, pl);
                if (k.HasValue) return k.Value;
            }
            var g = Curve(re.ByPowerLevel, p => p.DurationDays, pl);
            if (g.HasValue) return g.Value;
            NoteMissingCurve("runningEmpty.byPowerLevel durationDays",
                "The first-stage trait is not granted to anyone: without a duration the row "
                + "would carry a zero ExpiresTurn, which is how the game marks a trait "
                + "PERMANENT.");
            return null;
        }

        // Off-Duty duration, resolved the same way the first stage's is: a
        // Knight curve beats the general curve. Wired in 2.9.2 — before it,
        // offDuty.knight.byPowerLevel parsed and was never read, and Off-Duty
        // had no curve at all; since 2026-09-07 the curves are all there is.
        // Null means neither names a duration, and the caller does not escalate:
        // the merc keeps the first stage rather than being locked off the roster
        // permanently by a zero-day Off-Duty row.
        private static int? OffDutyDaysFor(bool knight, long pl)
        {
            var od = o.OffDuty;
            if (knight && od.Knight != null)
            {
                var k = Curve(od.Knight.ByPowerLevel, p => p.DurationDays, pl);
                if (k.HasValue) return k.Value;
            }
            var g = Curve(od.ByPowerLevel, p => p.DurationDays, pl);
            if (g.HasValue) return g.Value;
            NoteMissingCurve("offDuty.byPowerLevel durationDays",
                "Nobody is sent Off-Duty: without a duration the row would carry a zero "
                + "ExpiresTurn, which is how the game marks a trait PERMANENT, and the merc "
                + "would be off the roster for good. They keep the first stage instead.");
            return null;
        }

        // No curve value means no floor, which is NoMinAffected. Reported once so
        // "no floor" is a stated outcome rather than a silent zero.
        private static int MinAffectedFor(long pl)
        {
            var c = Curve(o.RunningEmpty.ByPowerLevel, p => p.MinAffected, pl);
            if (c.HasValue) return c.Value;
            NoteMissingCurve("runningEmpty.byPowerLevel minAffected",
                $"No floor is applied ({NoMinAffected}): the rolls alone decide how many mercs "
                + "take the first stage, and a mission where everybody passes fatigues nobody. "
                + "That is a legal way to configure this, so it is a warning rather than an "
                + "error.",
                false);
            return NoMinAffected;
        }

        // Null means no ceiling, and always has — that is this value's own
        // documented absent state, not a missing configuration, so it is not
        // reported. A curve that names maxAffected wins; nothing else is left to
        // try.
        private static int? MaxAffectedFor(long pl)
        {
            return Curve(o.RunningEmpty.ByPowerLevel, p => p.MaxAffected, pl);
        }

        // ---- Wound Resist ----------------------------------------------------

        // One point of resist per percentage point of chance, as ruled. The
        // floor keeps the result reachable so nobody is ever immune; the ceiling
        // is there because a merc at -80 resist against a 40% base would
        // otherwise be asked to roll under 120.
        private static int ThresholdFor(int chance, int resist, out bool floored)
        {
            // A configured chance of 0 means NO ROLL, whatever the resist, and
            // the code now does what the comment below has always said. It did
            // not: the floor is Math.Min(minChancePercent, chance), which is 0
            // when the chance is 0, and `chance - resist` against the NEGATIVE
            // resist most cyberware carries is positive — so 0% against a merc
            // at -25 came back as 25 and they fatigued a quarter of the time.
            // Returning here leaves every other path's arithmetic untouched.
            if (chance <= 0) { floored = false; return 0; }

            int v = chance - resist;

            // The floor bounds what RESIST is allowed to take away. It never
            // raises a chance that was already at or below it: a configured 0
            // means no roll, which is the natural way to switch fatigue off at
            // the low power levels, and a floor of 5 turning that into 5% is a
            // grant nobody asked for. So the effective floor is the configured
            // one or the base chance, whichever is lower.
            int floor = Math.Min(o.WoundResist.MinChancePercent, chance);
            floored = v < floor;
            if (floored) v = floor;
            if (v > 100) v = 100;
            return v;
        }

        private sealed class Resist
        {
            public int Total;
            public int Safehouse;
            public int Permanent;       // always-active, excluding the safehouse
            public int Timed;
            public int Gear;            // armour: the armor source and any ArmorEffect,
                                        // included in Total, not in Permanent/Timed
            public int Overlapped;      // counted once, seen twice
            public readonly List<SourceStats> Sources = new List<SourceStats>();
        }

        // What one reader returned for one merc. Run63 is why this exists: four
        // mercs logged "no resist" and nothing could say whether the readers
        // returned no rows, rows whose effects carry no WoundRes, or rows whose
        // effect this file never saw.
        private sealed class SourceStats
        {
            public string Name;
            public bool Unreadable;     // threw, returned null, or stopped part way
            public int Rows;            // rows walked
            public int Joined;          // effect taken from the row's own EffectData
            public int LookedUp;        // EffectData null; effect read from DataDb
            public int NoEffect;        // the content row names no effect (id 0)
            public int Unresolved;      // EffectData null and the lookup failed
            public int Carrying;        // effect carries a non-zero WoundRes
        }

        // How a row of each reader leads to its EffectModel when the joined
        // EffectData is null. Column names are read off CoreRPG_v1.dll's
        // property tables (2026-09-10): the content row is joined as `Join` on
        // the game row, or read by `Key` through DataDb.`ContentReader`, and its
        // `EffectColumn` is an EffectModel.EffectId for DataDb.ReadEffect. A
        // GameCharacterEffect row names its effect directly in EffectTypeId.
        // TraitModel.EffectTypeId is the same id space: trait 2009 -> 10507.
        private sealed class ResistSource
        {
            public string Name, Reader, Join, Key, ContentReader, EffectColumn;

            // The reader returns one row, not a list. Null, or a row whose Key
            // reads 0, is "carries none", not "could not read".
            public bool Single;

            // A second effect on the same row: the joined EffectModel, or the
            // EffectModel id to read when that join is null.
            public string SecondJoin, SecondKey;
        }

        private static readonly ResistSource[] ResistSources =
        {
            new ResistSource { Name = "trait", Reader = "ReadGameCharacterTraitsByCharacter",
                Join = "TraitData", Key = "TraitTypeId", ContentReader = "ReadTrait",
                EffectColumn = "EffectTypeId" },
            new ResistSource { Name = "effect", Reader = "ReadGameCharacterEffects",
                Key = "EffectTypeId" },
            new ResistSource { Name = "implant", Reader = "ReadGameCharacterImplants",
                Join = "ImplantData", Key = "ImplantTypeId", ContentReader = "ReadImplant",
                EffectColumn = "ImplantEffectId" },
            new ResistSource { Name = "job", Reader = "ReadGameCharacterJobNodes",
                Join = "NodeData", Key = "JobNodeId", ContentReader = "ReadJobNode",
                EffectColumn = "NodeEffect1Id" },

            // 2026-09-10. GameArmorModel (CoreRPG_v1.dll): CharacterId,
            // ArmorTypeId, GameEffectId; joined ArmorData (ArmorModel, which
            // carries ArmorEffectId), EffectData and EffectDataCrafted, both
            // typed EffectModel. EffectData is the armour's own effect.
            // EffectDataCrafted is the only EffectModel join matching
            // GameEffectId, which exists on no other model, so GameEffectId is
            // read as the crafted upgrade's EffectModel id [fitted].
            new ResistSource { Name = "armor", Reader = "ReadGameArmorByCharacter",
                Join = "ArmorData", Key = "ArmorTypeId", ContentReader = "ReadArmor",
                EffectColumn = "ArmorEffectId", Single = true,
                SecondJoin = "EffectDataCrafted", SecondKey = "GameEffectId" },
        };

        private static ResistSource SourceNamed(string name)
        {
            foreach (var src in ResistSources) if (src.Name == name) return src;
            return new ResistSource { Name = name, Reader = name };
        }

        // Sums every WoundRes source the ruling allows. Never throws: a reader
        // the game has renamed costs that source and logs, rather than costing
        // the mission its fatigue.
        private static Resist ResistFor(object db, long charId, object traitRows)
        {
            var r = new Resist();

            r.Safehouse = SafehouseResist(db);
            r.Total = r.Safehouse;

            // Only needed for rows that arrive without their joined EffectData;
            // null is handled, and reported, where a lookup needs it.
            var data = DataDbOf(db);

            // One grant can be mirrored in more than one of these tables, so
            // every source is checked against the union of the ones before it.
            // Section 1 of the design asks whether the game writes a
            // GameCharacterEffect row alongside a GameCharacterTrait row for one
            // grant; an implant's effect can surface through the effect reader
            // the same way, and cyberware is the source that decides this whole
            // mechanic's balance, so counting one implant twice would roughly
            // double the penalty.
            //
            // Order matters only for which source gets the credit in the log.
            // Traits first because their rows are already in hand.
            var seen = new HashSet<long>();
            AddSourceRows(traitRows, r, seen, ResistSources[0], data);
            for (int k = 1; k < ResistSources.Length; k++)
            {
                var src = ResistSources[k];
                bool threw;
                var got = TryRead(db, src.Reader, charId, out threw);
                if (src.Single && !threw)
                {
                    // One row or none. A merc with no armour is a normal case,
                    // so null here is an empty list and not UNREADABLE. Whether
                    // the game returns null or a defaulted row for an unarmoured
                    // merc is [unverified]; both read as none.
                    var one = new List<object>();
                    if (got != null && Num(Get(got, src.Key)) != 0) one.Add(got);
                    got = one;
                }
                AddSourceRows(got, r, seen, src, data);
            }

            return r;
        }

        private static object TryRead(object db, string reader, long charId)
        {
            bool threw;
            return TryRead(db, reader, charId, out threw);
        }

        private static object TryRead(object db, string reader, long charId, out bool threw)
        {
            threw = false;
            try { return Call(db, reader, new[] { typeof(long) }, new object[] { charId }); }
            catch (Exception e)
            {
                threw = true;
                var inner = e.InnerException ?? e;
                Plugin.Log.LogWarning($"Fatigue: {reader}({charId}) threw "
                    + $"{inner.GetType().Name}: {inner.Message}. That source contributes 0.");
                return null;
            }
        }

        // GameDb carries its DataDb as `dataDb` (CoreRPG_v1.dll, GameDb's
        // property table). The other two names are the DataLayer's spelling,
        // tried in case a build moves it.
        private static object DataDbOf(object db)
        {
            foreach (var name in new[] { "dataDb", "DataDb", "DataDBI" })
            {
                var d = Get(db, name);
                if (d != null) return d;
            }
            return null;
        }

        // Kept for the offline checks, which call AddRows by name with four
        // arguments. No DataDb, so a row without EffectData stays unresolved.
        private static void AddRows(object rows, Resist r, HashSet<long> seen, string source)
            => AddSourceRows(rows, r, seen, SourceNamed(source), null);

        // `seen` carries the effect ids already counted from EARLIER sources and
        // suppresses them here. Ids from THIS source merge in only after the
        // whole source is walked, because two rows in one table are two real
        // grants and both count — a merc carrying the same trait twice is not
        // an overlap. Pass null for a source that should not participate.
        private static void AddSourceRows(object rows, Resist r, HashSet<long> seen,
                                          ResistSource src, object data)
        {
            var st = new SourceStats { Name = src.Name };
            r.Sources.Add(st);

            if (rows == null)
            {
                // TryRead has already logged a throw; a reader that RETURNED null
                // has not, and used to read exactly like a merc with nothing.
                st.Unreadable = true;
                if (resistNoted.Add("null|" + src.Name))
                    Plugin.Log.LogWarning($"Fatigue: {src.Reader} gave no list, so {src.Name} "
                        + "Wound Resist counts 0 for that merc. The roll line says UNREADABLE "
                        + "wherever this happens. Reported once.");
                return;
            }

            bool complete;
            var list = Rows(rows, out complete);
            if (!complete) st.Unreadable = true;   // Rows() has said why, once

            var mine = seen != null ? new HashSet<long>() : null;
            foreach (var row in list)
            {
                st.Rows++;
                var effects = new List<object>(2);
                var first = EffectOf(row, src, data, st);
                if (first != null) effects.Add(first);
                if (src.SecondJoin != null)
                {
                    var second = SecondEffectOf(row, src, data, st);
                    if (second != null) effects.Add(second);
                }
                foreach (var eff in effects) AddEffect(eff, row, r, seen, mine, src, st);
            }

            if (mine != null) foreach (var id in mine) seen.Add(id);

            NoteSource(src, st);
        }

        // One effect's WoundRes into the sum. Split out of AddSourceRows on
        // 2026-09-10 because an armour row carries two effects.
        private static void AddEffect(object eff, object row, Resist r, HashSet<long> seen,
                                      HashSet<long> mine, ResistSource src, SourceStats st)
        {
            long points = Num(Get(eff, "WoundRes"));
            if (points == 0) return;
            st.Carrying++;

            long cls = Num(Get(eff, "EffectClassification"));

            long effId = Num(Get(eff, "EffectId"));
            if (seen != null && effId != 0 && seen.Contains(effId))
            {
                r.Overlapped += (int)points;
                if (!notedTraitEffectOverlap)
                {
                    notedTraitEffectOverlap = true;
                    Plugin.Log.LogInfo($"Fatigue: effect {effId} reached this merc through an "
                        + $"earlier source and again as a \"{src.Name}\" row. Counted once. The "
                        + "game does write one grant into more than one table — worth "
                        + "knowing, it was an open question in the design.");
                }
                return;
            }
            if (mine != null && effId != 0) mine.Add(effId);

            r.Total += (int)points;

            // Armour, from the armor source or as an ArmorEffect through any
            // other reader, is reported as gear rather than split by timing.
            if (src.Name == "armor" || cls == ClassArmorEffect) { r.Gear += (int)points; return; }

            // A trait's own ExpiresTurn overrides its classification: the
            // game sweeps on exactly that column, so a trait carrying one is
            // timed whatever kind of effect it points at.
            bool timed = TimedClasses.Contains(cls)
                      || (src.Name == "trait" && Num(Get(row, "ExpiresTurn")) != 0);
            if (timed) r.Timed += (int)points; else r.Permanent += (int)points;
        }

        private static void NoteSource(ResistSource src, SourceStats st)
        {
            if (st.LookedUp > 0 && resistNoted.Add("lookup|" + src.Name))
                Plugin.Log.LogInfo($"Fatigue: {src.Reader} returned rows with no joined "
                    + $"EffectData ({st.LookedUp} of {st.Rows} for this merc). Their effects were "
                    + "read from DataDb instead"
                    + (src.ContentReader != null
                       ? $" ({src.Join} or {src.ContentReader}({src.Key}) -> {src.EffectColumn} -> "
                         + "ReadEffect)" : $" ({src.Key} -> ReadEffect)")
                    + ". Said once per reader.");
            if (st.Unresolved > 0 && resistNoted.Add("unresolved|" + src.Name))
                Plugin.Log.LogWarning($"Fatigue: {st.Unresolved} {src.Name} row(s) had no joined "
                    + "EffectData and the DataDb lookup could not find their effect, so they "
                    + "count 0. The roll line says UNRESOLVED wherever this happens. Reported "
                    + "once per reader.");
        }

        // The armour's crafted upgrade: EffectDataCrafted when joined, else
        // GameEffectId read through DataDb.ReadEffect. 0 means no upgrade and
        // is not counted as anything.
        private static object SecondEffectOf(object row, ResistSource src, object data,
                                             SourceStats st)
        {
            var eff = Get(row, src.SecondJoin);
            if (eff != null) { st.Joined++; return eff; }
            long id;
            if (!TryNum(Get(row, src.SecondKey), out id)) { st.Unresolved++; return null; }
            if (id == 0) return null;
            eff = Lookup(data, "ReadEffect", id);
            if (eff == null) { st.Unresolved++; return null; }
            st.LookedUp++;
            return eff;
        }

        // The row's joined EffectData when the reader filled it, otherwise the
        // effect its content row names, read from DataDb. Null when there is no
        // effect to count; `st` records which of those it was.
        private static object EffectOf(object row, ResistSource src, object data, SourceStats st)
        {
            var eff = Get(row, "EffectData");
            if (eff != null) { st.Joined++; return eff; }

            long effectId;
            if (src.ContentReader == null)
            {
                if (!TryNum(Get(row, src.Key), out effectId)) { st.Unresolved++; return null; }
            }
            else
            {
                var content = src.Join != null ? Get(row, src.Join) : null;
                if (content == null)
                {
                    long key;
                    if (!TryNum(Get(row, src.Key), out key) || key == 0)
                    { st.Unresolved++; return null; }
                    content = Lookup(data, src.ContentReader, key);
                    if (content == null) { st.Unresolved++; return null; }
                }
                if (!TryNum(Get(content, src.EffectColumn), out effectId))
                { st.Unresolved++; return null; }
            }

            // A content row that names no effect is a legitimate nothing: most
            // job nodes grant a talent, not an effect.
            if (effectId == 0) { st.NoEffect++; return null; }

            eff = Lookup(data, "ReadEffect", effectId);
            if (eff == null) { st.Unresolved++; return null; }
            st.LookedUp++;
            return eff;
        }

        // One DataDb read by id, cached for the mission. A reader that throws
        // or is missing is reported once and costs its rows, never the roll.
        private static object Lookup(object data, string reader, long id)
        {
            if (data == null)
            {
                if (resistNoted.Add("nodatadb"))
                    Plugin.Log.LogWarning("Fatigue: a resist row needed a DataDb lookup and "
                        + "GameDb.dataDb read null, so rows without a joined EffectData count 0. "
                        + "Reported once.");
                return null;
            }

            var cacheKey = reader + ":" + id;
            object hit;
            if (lookupCache.TryGetValue(cacheKey, out hit)) return hit;

            object row = null;
            try { row = Call(data, reader, new[] { typeof(long) }, new object[] { id }); }
            catch (Exception e)
            {
                var inner = e.InnerException ?? e;
                if (resistNoted.Add("threw|" + reader))
                    Plugin.Log.LogWarning($"Fatigue: DataDb.{reader}({id}) threw "
                        + $"{inner.GetType().Name}: {inner.Message}. Rows that need it count 0 "
                        + "toward Wound Resist. Reported once.");
            }
            lookupCache[cacheKey] = row;
            return row;
        }

        // The safehouse total is the same for every merc and does not change
        // mid-mission, so it is read once per MISSION — Resolve clears
        // safehouseRead on each resolution, which this comment used to describe
        // wrongly as once per session. Three paths, because the
        // computed property read 0 on a row dumped straight out of the reader —
        // its Modules dictionary was not populated on that path — and a silent 0
        // here would quietly delete the Triage Clinic from the mechanic.
        private static int SafehouseResist(object db)
        {
            if (safehouseRead) return safehouseResist;
            safehouseRead = true;

            try
            {
                var houses = Call(db, "ReadGameSafehouses", Type.EmptyTypes, new object[0]);
                object house = null;
                int count = 0;
                foreach (var h in Rows(houses)) { if (count++ == 0) house = h; }
                if (house == null)
                {
                    if (loggedSafehouseValue != 0)
                    {
                        loggedSafehouseValue = 0;
                        Plugin.Log.LogInfo("Fatigue: no safehouse row, so no safehouse Wound "
                                         + "Resist.");
                    }
                    return safehouseResist = 0;
                }
                if (count > 1)
                    Plugin.Log.LogWarning($"Fatigue: {count} safehouses returned; using the first. "
                        + "The shipped save has exactly one, so this is new behaviour worth a look.");

                int computed = (int)Num(Get(house, "GetWoundRes"));
                var summary = Get(house, "ModuleSummary");
                int fromSummary = summary != null ? (int)Num(Get(summary, "WoundRes")) : 0;

                int fromModules = 0;
                foreach (var m in Rows(Get(house, "Modules")))
                {
                    var data = Get(m, "ModuleData");
                    if (data != null) fromModules += (int)Num(Get(data, "WoundRes"));
                }

                // Prefer the game's own number; fall back only when it is zero
                // and something else disagrees, which is the unpopulated-Modules
                // case rather than a genuine zero.
                safehouseResist = computed != 0 ? computed
                                : fromSummary != 0 ? fromSummary
                                : fromModules;

                // Logged when the number CHANGES rather than once a session, so
                // re-reading per mission does not fill the log while a Triage
                // Clinic upgrade still announces itself.
                if (safehouseResist != loggedSafehouseValue)
                {
                    loggedSafehouseValue = safehouseResist;
                    Plugin.Log.LogInfo($"Fatigue: safehouse Wound Resist {safehouseResist:+#;-#;0} "
                        + $"(GetWoundRes {computed}, ModuleSummary {fromSummary}, modules "
                        + $"{fromModules}). A Triage Clinic is worth +10/+15/+20/+30 by level.");
                    if (computed == 0 && (fromSummary != 0 || fromModules != 0))
                        Plugin.Log.LogWarning("Fatigue: GetWoundRes read 0 while the modules did "
                            + "not — the safehouse's Modules dictionary was not populated on this "
                            + "read path. Using the modules.");
                }
                return safehouseResist;
            }
            catch (Exception e)
            {
                var inner = e.InnerException ?? e;
                Plugin.Log.LogWarning($"Fatigue: reading the safehouse threw "
                    + $"{inner.GetType().Name}: {inner.Message}. Safehouse Wound Resist counts 0.");
                return safehouseResist = 0;
            }
        }

        // ---- writes ----------------------------------------------------------

        // Route A, construct. Run44 settled this against Route B (borrow an
        // existing row and overwrite it): Activator.CreateInstance allocates a
        // usable il2cpp object, and a borrowed row arrives carrying its source's
        // id, which an insert could write over.
        private static bool Apply(object db, long charId, long traitId, long turn, int days,
                                  string why)
        {
            var traitType = ResolveType(TraitModelTypeName);
            if (traitType == null) return false;

            object row;
            try { row = Activator.CreateInstance(traitType); }
            catch (Exception e)
            {
                Plugin.Log.LogError($"Fatigue: building a trait row threw {e.GetType().Name}: "
                                  + e.Message);
                return false;
            }

            long expires = turn + (long)days * TurnsPerDay;

            // EVERY Set is checked. Set returns false and logs when the property
            // is missing, read-only, or the conversion throws, and all nine
            // returns used to be dropped and the row inserted regardless. A
            // renamed ExpiresTurn left the field at 0, which is how this file's
            // own rules (Validate, CheckLevels) say the game marks a trait
            // PERMANENT — so one reflection miss wrote a save-resident trait the
            // mod cannot take back. A missed CharacterId wrote an orphan row on
            // character 0.
            //
            // None of the nine is treated as optional. What a constructed il2cpp
            // row holds in a column that did not take is not readable from this
            // source, so a column that failed to write is UNKNOWN rather than
            // zero, and a row with unknown columns is not one to put in a save.
            var unwritten = new List<string>();
            if (!Set(row, "Id", 0L)) unwritten.Add("Id");
            if (!Set(row, "CharacterId", charId)) unwritten.Add("CharacterId");
            if (!Set(row, "TraitTypeId", traitId)) unwritten.Add("TraitTypeId");
            if (!Set(row, "OptionId", 0L)) unwritten.Add("OptionId");
            if (!Set(row, "IsWound", 0L)) unwritten.Add("IsWound");
            if (!Set(row, "Description", "")) unwritten.Add("Description");
            if (!Set(row, "CreatedTurn", turn)) unwritten.Add("CreatedTurn");
            if (!Set(row, "ExpiresTurn", expires)) unwritten.Add("ExpiresTurn");
            if (!Set(row, "IsNew", 1L)) unwritten.Add("IsNew");
            // TraitData, EffectData and MatrixEffectData are joined content rows
            // rather than columns, and they fill themselves in: Run44 saw a
            // constructed row go in with all three null and come back out of
            // ReadGameCharacterTraitsByCharacter fully joined. Nothing to do.

            if (unwritten.Count > 0)
            {
                // Validate refuses this exact outcome — a permanent trait, a row
                // on the wrong character — when config is what would produce it.
                // The reflection path is as loud.
                Plugin.Log.LogError("Fatigue: could not write " + string.Join(", ", unwritten)
                    + $" on a {traitType.Name} for trait {traitId} on {charId} ({why}). NO ROW WAS "
                    + "INSERTED. A row with those columns unset would be wrong in your save rather "
                    + "than merely missing — an unset ExpiresTurn is how the game marks a trait "
                    + "PERMANENT, and an unset CharacterId puts it on character 0. Point "
                    + "CKFDataDump's [Diagnostics] DumpMembers at " + TraitModelTypeName
                    + " and compare.");
                return false;
            }

            try
            {
                long newId = Num(Call(db, "InsertGameCharacterTrait", new[] { traitType },
                                      new object[] { row }));
                if (newId == 0)
                {
                    Plugin.Log.LogError($"Fatigue: insert returned 0 for trait {traitId} on "
                        + $"{charId} ({why}). No exception, but no row either.");
                    return false;
                }
                if (o.LogGrants)
                    Plugin.Log.LogInfo($"Fatigue:     +++ row {newId}: trait {traitId} on "
                        + $"{charId} ({why}), created {turn}, expires {expires}");
                return true;
            }
            catch (Exception e)
            {
                var inner = e.InnerException ?? e;
                Plugin.Log.LogError($"Fatigue: INSERT THREW {inner.GetType().Name}: "
                    + $"{inner.Message} — trait {traitId} on {charId} ({why})");
                return false;
            }
        }

        private static void Revoke(object db, long charId, long rowId)
        {
            try
            {
                var n = Call(db, "DeleteGameCharacterTrait", new[] { typeof(long) },
                             new object[] { rowId });
                if (o.LogGrants)
                    Plugin.Log.LogInfo($"Fatigue:     --- row {rowId} removed from {charId} "
                                     + $"(clearsRunningEmpty) -> {Str(n)}");
            }
            catch (Exception e)
            {
                var inner = e.InnerException ?? e;
                // The escalation itself already went in, so the merc is locked
                // out either way. This only costs them the first stage lingering
                // underneath until it expires on its own.
                Plugin.Log.LogError($"Fatigue: DELETE THREW {inner.GetType().Name}: "
                    + $"{inner.Message} — row {rowId} on {charId}. The Off-Duty grant stands.");
            }
        }

        // splitmix64 over (turn, characterId). Stable across sessions and
        // machines, which is what makes reloading the victory screen reproduce
        // the same outcome instead of turning fatigue into a reroll button. Run47
        // checked this against values computed offline before the run: turn 1388
        // gave 27, 61 and 97 for characters 1, 16 and 19, exactly as predicted.
        // Do not change the constants without accepting that every save's future
        // rolls change with them.
        private static int StableRoll(long turn, long who)
        {
            unchecked
            {
                ulong z = (ulong)turn * 0x9E3779B97F4A7C15UL + (ulong)who;
                z += 0x9E3779B97F4A7C15UL;
                z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9UL;
                z = (z ^ (z >> 27)) * 0x94D049BB133111EBUL;
                z ^= z >> 31;
                return (int)(z % 100UL);
            }
        }

        // ---- reflection helpers ----------------------------------------------
        //
        // Deliberately local rather than reaching for Accessors: these run a few
        // dozen times per mission, not per row, and this file resolving its own
        // members keeps it independent of the rule engine's caches.

        private static object Call(object db, string name, Type[] sig, object[] args)
        {
            if (db == null) throw new InvalidOperationException("no GameDb");
            MethodInfo m = null;
            for (var t = db.GetType(); t != null && m == null; t = t.BaseType)
                m = t.GetMethod(name,
                    BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance,
                    null, sig, null);
            if (m == null)
                throw new MissingMethodException(db.GetType().Name + "." + name);
            return m.Invoke(db, args);
        }

        private static readonly Dictionary<Type, Dictionary<string, PropertyInfo>> PropCache =
            new Dictionary<Type, Dictionary<string, PropertyInfo>>();

        // A model's columns live on its *Base type, not on the leaf, so this has
        // to walk the hierarchy. A flat GetProperties with non-public flags
        // returns non-public members only for the type itself.
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
            if (p == null) return null;
            try { return p.GetValue(row); } catch { return null; }
        }

        private static bool Set(object row, string name, object value)
        {
            if (row == null) return false;
            var p = Prop(row.GetType(), name);
            if (p == null)
            {
                Plugin.Log.LogWarning($"Fatigue: no column named {name} on {row.GetType().Name}.");
                return false;
            }
            if (!p.CanWrite)
            {
                Plugin.Log.LogWarning($"Fatigue: {name} is read-only on {row.GetType().Name}.");
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
                Plugin.Log.LogWarning($"Fatigue: setting {name} threw {e.GetType().Name}: "
                                    + e.Message);
                return false;
            }
        }

        // Count / this[i] on the Il2Cpp list the reader hands back, through the
        // same ListShape the rule engine uses. GameSafehouseModel.Modules is a
        // Dictionary rather than a List, so an indexer miss falls through to its
        // Values collection and then to plain IEnumerable.
        //
        // `complete` is false whenever the caller must not conclude anything
        // from a row being ABSENT: a Count that threw, an element that came back
        // null, an enumerator that stopped early. This used to use
        // ListShape.Count, which reports both "empty" and "Count threw" as 0 and
        // logs neither — so an unreadable trait list looked exactly like a merc
        // with no traits and the mod granted them another row every mission.
        // ListShape.TryCount exists for that distinction and Elapse.ReadRows is
        // the model for the rest of this.
        private static List<object> Rows(object list, out bool complete)
        {
            var rows = new List<object>();
            complete = false;
            if (list == null) return rows;          // null is not an empty list

            var shape = ListShape.For(list.GetType());
            if (shape != null && shape.Usable)
            {
                int n;
                if (!shape.TryCount(list, out n))
                {
                    NotePartial(list, "its Count could not be read");
                    return rows;
                }
                for (int i = 0; i < n; i++)
                {
                    var row = shape.At(list, i);
                    if (row == null)
                    {
                        NotePartial(list, "an element could not be read");
                        return rows;
                    }
                    rows.Add(row);
                }
                complete = true;
                return rows;
            }

            var values = Get(list, "Values");
            var en = (values ?? list) as System.Collections.IEnumerable;
            if (en == null || list is string)
            {
                NotePartial(list, "it exposes neither Count/this[i] nor IEnumerable");
                return rows;
            }
            System.Collections.IEnumerator it;
            try { it = en.GetEnumerator(); }
            catch (Exception e)
            {
                NotePartial(list, "GetEnumerator threw " + e.GetType().Name);
                return rows;
            }
            while (true)
            {
                object cur;
                try { if (!it.MoveNext()) break; cur = it.Current; }
                catch (Exception e)
                {
                    NotePartial(list, "enumerating it threw " + e.GetType().Name);
                    return rows;
                }
                // A null element is a row that could not be read, not a row that
                // is not there, so it ends the read the same way a throw does.
                if (cur == null)
                {
                    NotePartial(list, "an element came back null");
                    return rows;
                }
                rows.Add(cur);
            }
            complete = true;
            return rows;
        }

        // The lenient overload, for reads whose result only reaches a log line
        // or a resist total that already reports a missing source as 0. Anything
        // DECIDING a write takes the two-argument form and checks the flag.
        private static IEnumerable<object> Rows(object list)
        {
            bool complete;
            return Rows(list, out complete);
        }

        // One line per list type, not one per mission.
        private static void NotePartial(object list, string why)
        {
            var what = list.GetType().Name;
            if (!unreadableWarned.Add("list|" + what)) return;
            Plugin.Log.LogWarning($"Fatigue: a {what} could not be read all the way through — "
                + why + ". Callers that decide a write treat that as \"cannot look\" rather than "
                + "\"nothing there\", so the mercs involved are skipped. Reported once.");
        }

        private static long Num(object v)
        {
            long n;
            return TryNum(v, out n) ? n : 0;
        }

        // Num() collapses "could not read" into 0. On any path that decides a
        // write, or that keys a merc, that difference is the one that matters:
        // an unreadable TraitTypeId read as 0 makes every merc look untouched,
        // so nobody is ever escalated and the row granted last mission is
        // invisible to the next one. Elapse.cs carries the same pair.
        private static bool TryNum(object v, out long n)
        {
            n = 0;
            if (v == null) return false;
            try { n = Convert.ToInt64(v, CultureInfo.InvariantCulture); return true; }
            catch { return false; }
        }

        // Each distinct (model, column) reported once. Get() returns null both
        // for a property this file cannot find and for one that threw, and it
        // says nothing on either — Set() has always logged its misses.
        private static void NoteUnreadable(string model, string column)
        {
            if (!unreadableWarned.Add(model + "." + column)) return;
            Plugin.Log.LogWarning($"Fatigue: {model}.{column} came back null or unconvertible on "
                + "at least one row. It is refused rather than read as 0, so the merc or the row "
                + "it belongs to is skipped. Reported once.");
        }

        private static string Str(object v)
        {
            try { return v == null ? "" : v.ToString(); } catch { return ""; }
        }
    }
}
