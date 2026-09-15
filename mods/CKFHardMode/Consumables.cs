// Consumables — the six consumable lever sheets, expanded into rules at load.
//
// WHY THIS IS A FOURTH EXPANDER
//
// GearClasses.cs expands ONE row into writes across MANY rows of ONE table.
// Cyberweapons.cs and Implants.cs each expand ONE row into TWO rows in TWO
// tables. A consumable row is the same shape again with one more table on the
// end: ONE ROW IS UP TO FOUR ROWS IN UP TO FOUR TABLES.
//
//   ItemModel          keyed on ItemTypeId       price, rarity, power level
//   TalentModel        keyed on that row's TalentId        the talent levers
//   EffectModel        keyed on that row's EffectId        the payload
//   MatrixEffectModel  keyed on that row's MatrixEffectId  the matrix payload
//
// ItemModel is 73 rows of ten columns -- ItemName, ItemDesc, ItemTypeId,
// ItemClass, ServiceOptionId, LeverageClass, Rarity, PowerLevel, Cost, TalentId
// [measured, sheets/raw/ItemModel.csv] -- so every lever past price and rarity
// lives behind TalentId and every payload past that lives behind the talent's
// effect columns. A row that sets nothing on one side emits only the others.
//
// SIX SHEETS, BECAUSE THE LIVE COLUMNS BARELY OVERLAP
//
// Split by ItemClass: 1 medical (18 rows), 2 grenades (11), 3 devices (12),
// 4 chems (18), 6 sploitkits (3), 7 matrix (11). There is no ItemClass 5.
// 18+11+12+18+3+11 = 73. A grenade and a Juice share only MaxCharges, so a flat
// 73-row table would be about 70% empty and the lever-sheets spec forbids a
// column dead for its own rows. ItemClass itself is the SUB-TABLE KEY and is
// carried by no file, the same role ImplantSlot plays in Implants.cs.
//
// consumables-sploitkits.csv IS ItemModel ONLY, AND THAT IS NOT AN OVERSIGHT.
// Its three rows are ItemTypeId 1000, 1002 and 1003, all TalentId 0, and no
// TalentModel row with id 0 exists [measured, scripts/consumables.py's
// check_join()]. So the file carries no TalentId column, no EffectId column and
// five ItemModel levers, and SploitkitLevers below declares exactly that. A
// sheet that showed talent columns there would give the player rows that do
// nothing. The load line names the three tables this sheet cannot reach rather
// than leaving their absence to be inferred from a zero.
//
// THE Matrix PREFIX IS AN ALIAS ON THE PAYLOAD COLUMNS AND ONLY THERE
//
// EffectClassification and ActionPoints are live in BOTH effect tables
// [measured], so a bare header name on consumables-matrix.csv would map to two
// different (model, column) targets. Every MatrixEffectModel payload column is
// therefore aliased with a "Matrix" prefix in the header -- ALL of them, not
// only the two that collide, because a rule that applies to some of a table's
// columns is a rule nobody can check. cyberweapons.py's PureDamage ->
// PureDamage1 is the same device.
//
// THREE COLUMNS BEGINNING "Matrix" ARE NOT ALIASES AND MUST NOT BE STRIPPED:
//
//   MatrixEffect      a real TalentModel column (the talent's matrix-effect
//                     pointer). Target is MatrixEffect, not Effect.
//   MatrixDuration    a real TalentModel column. Target is MatrixDuration.
//   MatrixEffectId    an IDENTITY column. It keys the MatrixEffectModel rule
//                     and is never parsed as an adjustment.
//
// Stripping one of those would send a talent lever to the wrong table. The map
// below carries the target LITERALLY for every entry rather than computing it
// from the name, so there is no strip step to get wrong at runtime, and
// VerifyMap() re-derives the invariant at load and says what it checked.
//
// THE OPERATOR IS IN THE CELL, NOT THE HEADER
//
// Direct overlays (Overlays.cs) carry the operator as a header suffix --
// Column*, Column+ -- and every cell is a plain number. The lever sheets do the
// opposite: the header is a plain column name and the CELL carries the operator
// (blank, =N, +N, -N, xN), parsed by MissionRewards.Adjust.Parse. That is the
// dialect GearClasses.cs, Cyberweapons.cs and Implants.cs all use and this file
// uses it unchanged. There is no third dialect here.
//
// EVERY CELL SHIPS BLANK, AND THAT IS A MEASUREMENT
//
// 0 of the 270 rules in ckf.hardmode.rules.json select any of the 194
// consumable-reachable (table, id) pairs, and 0 rows across the overlay CSVs in
// ckf.hardmode.d do either [measured, reproduced by scripts/consumables.py's
// check_untouched() on every run]. 0 lever cells are non-blank across the six
// files today [measured, 2026-09-14]. So a correct load emits 0 rules from this
// file, and the load line says so IN WORDS with the row count beside it: "read
// 18 rows and every cell was blank" and "could not read the file at all" are
// different answers and this class never prints one for the other
// (AGENTS.md section 3).
//
// KEYS ARE (table, id), NEVER id ALONE
//
// 221 ids are both a TalentId and an EffectId; 130 are both an EffectId and a
// MatrixEffectId; 137 are both a MonsterTypeId and a WeaponId [measured].
// Inside this phase's own 194 pairs, 31 ids appear under two different models,
// so an id-alone key collapses 194 pairs to 163 and sends 31 writes to the
// wrong table [measured, 2026-09-14, reproduced against the six live files].
//
// The sharpest cases are inside ONE FILE:
//
//   consumables-medical.csv row 2 is TalentId 75006 AND EffectId 75006 -- one
//   sheet row writing TalentModel 75006 and EffectModel 75006, two different
//   rows of two different tables that share a number. Row 3 is 75012/75012 the
//   same way.
//
//   consumables-medical.csv row 9 has TalentId 75022 (Bio-Stitch Bandages) and
//   row 18 has EffectId 75022 (Mass Trauma Kit's effect). Two different rows of
//   the file, one number, two tables.
//
// Eight ids of consumables-medical.csv alone are both a TalentId and an EffectId
// of that file [measured]. The registry below is keyed on (model, id) and keeps
// every one of them apart.
//
// NO CLONE. EVER. design.md section 11 makes splitting a shared row an explicit
// per-row opt-in and this dialect does not carry one: _clone and _serveOn in a
// header REFUSE THE WHOLE FILE rather than being ignored. RowClone.cs is the
// path that produces a mission that will not load.
//
// TWO EFFECT ROWS ARE SHARED BY MORE THAN ONE ITEM, AND BOTH ARE EDITABLE HERE
//
//   EffectModel 76005  <- consumables-medical.csv rows 6 and 19
//                         (Patch X-Kit, Patch X-Kit Ultra; talents 75009, 75050)
//   EffectModel 76017  <- consumables-devices.csv rows 4, 8 and 10
//                         (Dazzler, Advanced Dazzler, LR-Max Dazzler;
//                          talents 75004, 75035, 75048)
//
// [measured, 2026-09-14, against the six live files] Both have every owner
// inside one file, so both are TWO OR THREE EDITORS OF ONE EffectModel ROW.
// Reconcile() below settles that before any rule is built, the way Implants.cs
// does, rather than letting the (model, id) registry keep whichever row arrived
// first: that would make the surviving edit depend on row order and could not
// name the other owners.
//
// EffectModel 75022 is NOT in that list and the difference matters. ONE talent
// (Mass Trauma Kit) carries it in BOTH SelfEffect and TargetEffect, so it has
// one owner named once on one line. A row cannot diverge from itself.

using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text.Json;

namespace CKFHardMode
{
    internal static class Consumables
    {
        internal const string MedicalSheet    = "consumables-medical.csv";
        internal const string GrenadeSheet    = "consumables-grenades.csv";
        internal const string DeviceSheet     = "consumables-devices.csv";
        internal const string ChemSheet       = "consumables-chems.csv";
        internal const string SploitkitSheet  = "consumables-sploitkits.csv";
        internal const string MatrixSheet     = "consumables-matrix.csv";

        internal const string ItemModel         = "ItemModel";
        internal const string TalentModel       = "TalentModel";
        internal const string EffectModel       = "EffectModel";
        internal const string MatrixEffectModel = "MatrixEffectModel";

        internal const string ItemKey   = "ItemTypeId";
        internal const string TalentKey = "TalentId";
        internal const string EffectKey = "EffectId";
        internal const string MatrixKey = "MatrixEffectId";

        /// <summary>The prefix that aliases a MatrixEffectModel payload column
        /// in a sheet header. It is NOT a general rule about names beginning
        /// "Matrix": see NotAliases below and the file header.</summary>
        internal const string MatrixAliasPrefix = "Matrix";

        /// <summary>One sheet column, and the one game column of the one game
        /// table it writes.</summary>
        internal sealed class Lever
        {
            internal readonly string Column;   // as it appears in the header
            internal readonly string Model;    // one of the four models above
            internal readonly string Target;   // the game column actually written

            internal Lever(string column, string model, string target)
            {
                Column = column; Model = model; Target = target;
            }
        }

        // THE COLUMN MAP. BEGIN LEVER MAP — this table is meant to be SCRAPED
        // the way scripts/cyberweapons.py's check_map_matches_plugin() scrapes
        // Cyberweapons.cs: read only between this marker and the closing one,
        // parse each Lever entry's column / model / target, group them by the
        // preceding `<Name>Levers =` line, and REFUSE if the markers are absent
        // or no entry parses — a scrape that matched nothing must not report
        // agreement (AGENTS.md section 3). The entry shape and the array-name
        // shape here are deliberately identical to Cyberweapons.cs's so that
        // reader's own regexes fit without a second dialect.
        //
        // THE MARKER TEXT MUST NOT APPEAR IN PROSE -- AND THIS FILE'S READER NOW
        // REFUSES RATHER THAN GUESSING WHEN IT DOES. scripts/consumables.py's
        // scrape_plugin_map() counts the marker LINES and requires EXACTLY ONE
        // of each; zero, or two or more, is a named P-MAP refusal, not a block
        // quietly resolved to the first occurrence. This file still declines to
        // spell either marker outside the two real ones, and should keep
        // declining: the rule turns a reflowed comment into a loud failure, it
        // does not make writing one safe.
        //
        // CORRECTION, 2026-09-14. The paragraph this replaces said "The reader
        // takes the FIRST occurrence of each marker string, so a comment that
        // spells either of them out in a sentence would close the block early
        // and the scrape would parse zero entries." That was written when
        // cyberweapons.py was the only reader of a map like this one, and it is
        // STILL TRUE OF THAT READER -- it does `src.find(_MAP_END)` and takes
        // whatever comes first. It is no longer true of this file's reader.
        //
        // WHY THE EXACTLY-ONE RULE IS WORTH A REFUSAL [measured 2026-09-14].
        // Implants.cs carries the opening marker once and the CLOSING one three
        // times: the real marker line at 211, plus two sentences of prose that
        // spell it out, at 146 and 692. A find()-style reader would close on the
        // one at line 146 -- one line below the opening marker -- and report
        // agreement over a block containing no entry at all. scripts/implants.py
        // escapes that a third way, with a line-anchored regex that matches a
        // marker only when it occupies its whole comment line, and it has a
        // selftest case (F23) for exactly this. cyberweapons.py gets away with
        // find() only because the closing phrase occurs in Cyberweapons.cs
        // exactly once: that file's own prose splits those words across a line
        // break, so the literal string never appears twice. That is a property
        // of one comment's line wrapping, not a guarantee, and it is a single
        // reflow away from being false.
        //
        // WIRED UP SINCE 2026-09-14 -- WHICH IS WHAT THIS BLOCK USED TO DENY.
        // scripts/consumables.py:2710 defines check_map_matches_plugin(); its
        // PLUGIN_SOURCE (line 2573) names this file; scrape_plugin_map() (2626)
        // applies the exactly-one rule above; and `map` is in ALL_CHECKS (2860)
        // and called from run_checks(), so --check and --selftest both compare
        // this table against the generator's -- entry for entry and in order,
        // across all six sheets -- and each array against that sheet's
        // generated header as well.
        //
        // CORRECTION, 2026-09-14, left standing because it is the claim a reader
        // would otherwise still act on. This block read: "NOT YET WIRED UP, SAID
        // RATHER THAN IMPLIED: scripts/consumables.py has its own marker pair
        // but NO check_map_matches_plugin() and no PLUGIN_SOURCE pointing here,
        // so as of this commit NOTHING COMPARES THIS TABLE TO ANYTHING. The
        // markers and the entry shape are in place so that the check is a
        // reader, not a rewrite; until it exists, the two transcriptions can
        // drift and no gate will say so. scripts/ is not this unit's directory
        // to write." Both halves are false now, and the last sentence is why it
        // lasted: the paragraph was written to be deleted by whichever commit
        // added the check, by an author who could not make that commit himself.
        // The check landed and the paragraph did not move. A comment that
        // accurately describes a gap is the most confident wrong thing in a file
        // the moment the gap closes -- so say which commit retires it, or expect
        // to find it here.
        //
        // THE TARGET IS LITERAL ON EVERY ENTRY. On the 126 entries whose model
        // is not MatrixEffectModel the target is the column name unchanged; on
        // the 11 MatrixEffectModel entries it is the column name with its
        // "Matrix" alias prefix removed. Writing it out rather than computing it
        // is what makes "never strip the prefix for an EffectModel target" a
        // property you can read off the page instead of a branch you have to
        // trust. VerifyMap() re-derives it at load anyway.
        //
        // ORDER IS HEADER ORDER, which is generator order: ItemModel columns,
        // then TalentModel, then EffectModel, then MatrixEffectModel, each in
        // its own dump-column order (scripts/consumables.py's columns_for()).
        // Identity columns (ItemName, ItemTypeId, TalentId, EffectId,
        // MatrixEffectId) and _comment are NOT levers and are not here.

        internal static readonly Lever[] MedicalLevers =
        {
            new Lever("ServiceOptionId",      ItemModel,   "ServiceOptionId"),
            new Lever("Rarity",               ItemModel,   "Rarity"),
            new Lever("PowerLevel",           ItemModel,   "PowerLevel"),
            new Lever("Cost",                 ItemModel,   "Cost"),
            new Lever("AlternateAdjustment",  TalentModel, "AlternateAdjustment"),
            new Lever("AltOverride",          TalentModel, "AltOverride"),
            new Lever("LevelCost",            TalentModel, "LevelCost"),
            new Lever("TalentIsActive",       TalentModel, "TalentIsActive"),
            new Lever("Range",                TalentModel, "Range"),
            new Lever("RangeAoE",             TalentModel, "RangeAoE"),
            new Lever("ActionId",             TalentModel, "ActionId"),
            new Lever("ApCost",               TalentModel, "ApCost"),
            new Lever("TargetEffect",         TalentModel, "TargetEffect"),
            new Lever("TargetEffectDuration", TalentModel, "TargetEffectDuration"),
            new Lever("SelfEffect",           TalentModel, "SelfEffect"),
            new Lever("Token",                TalentModel, "Token"),
            new Lever("TokenDuration",        TalentModel, "TokenDuration"),
            new Lever("PreReq",               TalentModel, "PreReq"),
            new Lever("FilterTypeId",         TalentModel, "FilterTypeId"),
            new Lever("MaxCharges",           TalentModel, "MaxCharges"),
            new Lever("TargetType",           TalentModel, "TargetType"),
            new Lever("EffectClassification", EffectModel, "EffectClassification"),
            new Lever("EffectHealType",       EffectModel, "EffectHealType"),
            new Lever("Heals",                EffectModel, "Heals"),
            new Lever("WoundRes",             EffectModel, "WoundRes"),
            new Lever("StressRes",            EffectModel, "StressRes"),
            new Lever("InitBonus",            EffectModel, "InitBonus"),
            new Lever("ActionPoints",         EffectModel, "ActionPoints"),
            new Lever("MovePoints",           EffectModel, "MovePoints"),
        };

        // PhysicalDamage AND BallisticDamage HERE ARE TalentModel COLUMNS, NOT
        // EffectModel ONES. Both names exist in both dump headers [measured,
        // sheets/raw/TalentModel.csv and sheets/raw/EffectModel.csv], and the
        // generator resolves them to TalentModel because it takes TalentModel
        // before EffectModel and they are non-zero on this class's own talents.
        // The literal target below is what settles it at runtime; nothing here
        // resolves a name against two tables and picks.
        internal static readonly Lever[] GrenadeLevers =
        {
            new Lever("ServiceOptionId",      ItemModel,   "ServiceOptionId"),
            new Lever("PowerLevel",           ItemModel,   "PowerLevel"),
            new Lever("Cost",                 ItemModel,   "Cost"),
            new Lever("AlternateAdjustment",  TalentModel, "AlternateAdjustment"),
            new Lever("LevelCost",            TalentModel, "LevelCost"),
            new Lever("TalentIsActive",       TalentModel, "TalentIsActive"),
            new Lever("Range",                TalentModel, "Range"),
            new Lever("RangeAoE",             TalentModel, "RangeAoE"),
            new Lever("ActionId",             TalentModel, "ActionId"),
            new Lever("ApCost",               TalentModel, "ApCost"),
            new Lever("TargetEffect",         TalentModel, "TargetEffect"),
            new Lever("TargetEffectDuration", TalentModel, "TargetEffectDuration"),
            new Lever("Token",                TalentModel, "Token"),
            new Lever("TokenDuration",        TalentModel, "TokenDuration"),
            new Lever("Volume",               TalentModel, "Volume"),
            new Lever("PureDamage",           TalentModel, "PureDamage"),
            new Lever("PhysicalDamage",       TalentModel, "PhysicalDamage"),
            new Lever("BallisticDamage",      TalentModel, "BallisticDamage"),
            new Lever("FilterTypeId",         TalentModel, "FilterTypeId"),
            new Lever("MaxCharges",           TalentModel, "MaxCharges"),
            new Lever("TargetType",           TalentModel, "TargetType"),
            new Lever("EffectClassification", EffectModel, "EffectClassification"),
            new Lever("EffectClearType",      EffectModel, "EffectClearType"),
            new Lever("EffectPurgeType",      EffectModel, "EffectPurgeType"),
            new Lever("Stunned",              EffectModel, "Stunned"),
        };

        internal static readonly Lever[] DeviceLevers =
        {
            new Lever("ServiceOptionId",      ItemModel,   "ServiceOptionId"),
            new Lever("Rarity",               ItemModel,   "Rarity"),
            new Lever("PowerLevel",           ItemModel,   "PowerLevel"),
            new Lever("Cost",                 ItemModel,   "Cost"),
            new Lever("AlternateAdjustment",  TalentModel, "AlternateAdjustment"),
            new Lever("AltOverride",          TalentModel, "AltOverride"),
            new Lever("LevelCost",            TalentModel, "LevelCost"),
            new Lever("TalentIsActive",       TalentModel, "TalentIsActive"),
            new Lever("Range",                TalentModel, "Range"),
            new Lever("RangeAoE",             TalentModel, "RangeAoE"),
            new Lever("ActionId",             TalentModel, "ActionId"),
            new Lever("ApCost",               TalentModel, "ApCost"),
            new Lever("TargetEffect",         TalentModel, "TargetEffect"),
            new Lever("TargetEffectDuration", TalentModel, "TargetEffectDuration"),
            new Lever("SelfEffect",           TalentModel, "SelfEffect"),
            new Lever("SelfDuration",         TalentModel, "SelfDuration"),
            new Lever("Token",                TalentModel, "Token"),
            new Lever("TokenCount",           TalentModel, "TokenCount"),
            new Lever("TokenDuration",        TalentModel, "TokenDuration"),
            new Lever("PreReq",               TalentModel, "PreReq"),
            new Lever("FilterTypeId",         TalentModel, "FilterTypeId"),
            new Lever("MaxCharges",           TalentModel, "MaxCharges"),
            new Lever("TargetType",           TalentModel, "TargetType"),
            new Lever("EffectClassification", EffectModel, "EffectClassification"),
            new Lever("EffectClearType",      EffectModel, "EffectClearType"),
            new Lever("EffectPurgeType",      EffectModel, "EffectPurgeType"),
            new Lever("PureDamageMelee",      EffectModel, "PureDamageMelee"),
            new Lever("Stunned",              EffectModel, "Stunned"),
        };

        internal static readonly Lever[] ChemLevers =
        {
            new Lever("ServiceOptionId",      ItemModel,   "ServiceOptionId"),
            new Lever("Rarity",               ItemModel,   "Rarity"),
            new Lever("PowerLevel",           ItemModel,   "PowerLevel"),
            new Lever("Cost",                 ItemModel,   "Cost"),
            new Lever("AlternateAdjustment",  TalentModel, "AlternateAdjustment"),
            new Lever("LevelCost",            TalentModel, "LevelCost"),
            new Lever("TalentIsActive",       TalentModel, "TalentIsActive"),
            new Lever("Range",                TalentModel, "Range"),
            new Lever("ApCost",               TalentModel, "ApCost"),
            new Lever("TargetEffect",         TalentModel, "TargetEffect"),
            new Lever("TargetEffectDuration", TalentModel, "TargetEffectDuration"),
            new Lever("SelfEffect",           TalentModel, "SelfEffect"),
            new Lever("SelfDuration",         TalentModel, "SelfDuration"),
            new Lever("FilterTypeId",         TalentModel, "FilterTypeId"),
            new Lever("MaxCharges",           TalentModel, "MaxCharges"),
            new Lever("TargetType",           TalentModel, "TargetType"),
            new Lever("EffectClassification", EffectModel, "EffectClassification"),
            new Lever("EffectPurgeType",      EffectModel, "EffectPurgeType"),
            new Lever("EffectHealType",       EffectModel, "EffectHealType"),
            new Lever("Heals",                EffectModel, "Heals"),
            new Lever("WoundRes",             EffectModel, "WoundRes"),
            new Lever("StressRes",            EffectModel, "StressRes"),
            new Lever("MeleeAttack",          EffectModel, "MeleeAttack"),
            new Lever("RangedAttack",         EffectModel, "RangedAttack"),
            new Lever("CritRate",             EffectModel, "CritRate"),
            new Lever("CritRateStealth",      EffectModel, "CritRateStealth"),
            new Lever("CritMultiBase",        EffectModel, "CritMultiBase"),
            new Lever("PureDamageBallistic",  EffectModel, "PureDamageBallistic"),
            new Lever("PureDamageMelee",      EffectModel, "PureDamageMelee"),
            new Lever("PhysicalArmor",        EffectModel, "PhysicalArmor"),
            new Lever("BallisticArmor",       EffectModel, "BallisticArmor"),
            new Lever("Evasion",              EffectModel, "Evasion"),
            new Lever("DetectRangeReduction", EffectModel, "DetectRangeReduction"),
            new Lever("RecoilBonus",          EffectModel, "RecoilBonus"),
            new Lever("RecoilRate",           EffectModel, "RecoilRate"),
            new Lever("MoveSpeed",            EffectModel, "MoveSpeed"),
            new Lever("InitBonus",            EffectModel, "InitBonus"),
            new Lever("ActionPoints",         EffectModel, "ActionPoints"),
            new Lever("MovePoints",           EffectModel, "MovePoints"),
        };

        // FIVE ItemModel LEVERS AND NOTHING ELSE. See the file header: all three
        // rows are TalentId 0 and no TalentModel row with id 0 exists, so there
        // is no talent half and no payload half to declare. LeverageClass is
        // live ONLY here among the six sheets.
        internal static readonly Lever[] SploitkitLevers =
        {
            new Lever("ServiceOptionId",      ItemModel,   "ServiceOptionId"),
            new Lever("LeverageClass",        ItemModel,   "LeverageClass"),
            new Lever("Rarity",               ItemModel,   "Rarity"),
            new Lever("PowerLevel",           ItemModel,   "PowerLevel"),
            new Lever("Cost",                 ItemModel,   "Cost"),
        };

        // THE ALIAS SHEET. Read the two blocks at the bottom together:
        //
        //   MatrixEffect / MatrixDuration  ->  TalentModel, target UNCHANGED.
        //       Real TalentModel columns. Stripping the prefix would aim a
        //       talent lever at MatrixEffectModel columns called "Effect" and
        //       "Duration", neither of which exists.
        //   Matrix<Name>                   ->  MatrixEffectModel, target
        //       <Name>. Eleven of them, every payload column of the table this
        //       sheet reaches, aliased whether or not the bare name collides.
        //
        // EffectClassification (unprefixed, EffectModel) and
        // MatrixEffectClassification (prefixed, MatrixEffectModel) are both
        // present below and are the collision the alias exists for; ActionPoints
        // and MatrixActionPoints are the other one.
        internal static readonly Lever[] MatrixLevers =
        {
            new Lever("ServiceOptionId",            ItemModel,         "ServiceOptionId"),
            new Lever("Rarity",                     ItemModel,         "Rarity"),
            new Lever("PowerLevel",                 ItemModel,         "PowerLevel"),
            new Lever("Cost",                       ItemModel,         "Cost"),
            new Lever("AlternateAdjustment",        TalentModel,       "AlternateAdjustment"),
            new Lever("LevelCost",                  TalentModel,       "LevelCost"),
            new Lever("TalentIsMatrixOnly",         TalentModel,       "TalentIsMatrixOnly"),
            new Lever("TalentIsActive",             TalentModel,       "TalentIsActive"),
            new Lever("ApCost",                     TalentModel,       "ApCost"),
            new Lever("SelfEffect",                 TalentModel,       "SelfEffect"),
            new Lever("SelfDuration",               TalentModel,       "SelfDuration"),
            new Lever("MatrixEffect",               TalentModel,       "MatrixEffect"),
            new Lever("MatrixDuration",             TalentModel,       "MatrixDuration"),
            new Lever("MaxCharges",                 TalentModel,       "MaxCharges"),
            new Lever("TargetType",                 TalentModel,       "TargetType"),
            new Lever("EffectClassification",       EffectModel,       "EffectClassification"),
            new Lever("WoundRes",                   EffectModel,       "WoundRes"),
            new Lever("StressRes",                  EffectModel,       "StressRes"),
            new Lever("FiringArc",                  EffectModel,       "FiringArc"),
            new Lever("CritRate",                   EffectModel,       "CritRate"),
            new Lever("PureDamageBallistic",        EffectModel,       "PureDamageBallistic"),
            new Lever("PureDamageMelee",            EffectModel,       "PureDamageMelee"),
            new Lever("ArmorCrit",                  EffectModel,       "ArmorCrit"),
            new Lever("DmgReduction",               EffectModel,       "DmgReduction"),
            new Lever("RecoilBonus",                EffectModel,       "RecoilBonus"),
            new Lever("RecoilRate",                 EffectModel,       "RecoilRate"),
            new Lever("MoveSpeedMitigate",          EffectModel,       "MoveSpeedMitigate"),
            new Lever("ActionPoints",               EffectModel,       "ActionPoints"),
            new Lever("MatrixEffectClassification", MatrixEffectModel, "EffectClassification"),
            new Lever("MatrixInstant",              MatrixEffectModel, "Instant"),
            new Lever("MatrixActionPoints",         MatrixEffectModel, "ActionPoints"),
            new Lever("MatrixIoBoost",              MatrixEffectModel, "IoBoost"),
            new Lever("MatrixDamageBoost",          MatrixEffectModel, "DamageBoost"),
            new Lever("MatrixHealConnection",       MatrixEffectModel, "HealConnection"),
            new Lever("MatrixDeckArmor",            MatrixEffectModel, "DeckArmor"),
            new Lever("MatrixDeckShield",           MatrixEffectModel, "DeckShield"),
            new Lever("MatrixPrePostBlocked",       MatrixEffectModel, "PrePostBlocked"),
            new Lever("MatrixSecurityTally",        MatrixEffectModel, "SecurityTally"),
            new Lever("MatrixSCUTurns",             MatrixEffectModel, "SCUTurns"),
        };

        // The three header names that BEGIN with the alias prefix and are NOT
        // aliases. VerifyMap() asserts none of them is ever carried as a
        // MatrixEffectModel lever. See the file header for what stripping one
        // would do.
        internal static readonly string[] NotAliases =
        {
            "MatrixEffect", "MatrixDuration", MatrixKey,
        };
        // END LEVER MAP

        // The five identity columns. NONE of them is a lever: a value in one is
        // never parsed as an adjustment, which is why an ItemTypeId of 5404 does
        // not become "set ItemTypeId to 5404". Phase 6 hit that trap the other
        // way round on the claw sheet — the editor's first count of "override
        // cells filled" came back 32 and they were all identity.
        //
        // A sheet carries only the identity columns its rows can use:
        // consumables-sploitkits.csv has ItemName and ItemTypeId and no others,
        // and consumables-matrix.csv is the only one carrying MatrixEffectId.
        // Membership is what is tested, so a sheet missing one is not a fault.
        internal static readonly string[] Identity =
        {
            "ItemName", ItemKey, TalentKey, EffectKey, MatrixKey,
        };

        // Control columns. `_comment` is accepted and ignored; the two below
        // REFUSE THE WHOLE FILE. See the header on why a clone is never
        // automatic.
        internal static readonly Dictionary<string, string> RefusedControl =
            new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
        {
            { "_clone", "a clone is never emitted from a lever sheet. RowClone.cs is "
                      + "the path that produces a mission that will not load, and "
                      + "design.md section 11 makes splitting a shared row an explicit "
                      + "per-row opt-in that this dialect does not carry." },
            { "_serveOn", "serveOn belongs to a clone rule, and these sheets emit none." },
        };

        private static readonly HashSet<string> IdentitySet =
            new HashSet<string>(Identity, StringComparer.Ordinal);

        private static readonly HashSet<string> NotAliasSet =
            new HashSet<string>(NotAliases, StringComparer.Ordinal);

        /// <summary>Sheet filename to its declared levers. Keyed
        /// case-insensitively, the way Owns compares.</summary>
        private static readonly Dictionary<string, Lever[]> Sheets =
            new Dictionary<string, Lever[]>(StringComparer.OrdinalIgnoreCase)
        {
            { MedicalSheet,   MedicalLevers   },
            { GrenadeSheet,   GrenadeLevers   },
            { DeviceSheet,    DeviceLevers    },
            { ChemSheet,      ChemLevers      },
            { SploitkitSheet, SploitkitLevers },
            { MatrixSheet,    MatrixLevers    },
        };

        /// <summary>The key column of each model, for the rule's `where`.</summary>
        private static readonly Dictionary<string, string> KeyColumnOf =
            new Dictionary<string, string>(StringComparer.Ordinal)
        {
            { ItemModel,         ItemKey   },
            { TalentModel,       TalentKey },
            { EffectModel,       EffectKey },
            { MatrixEffectModel, MatrixKey },
        };

        /// <summary>Emission order, fixed so one row's rules always arrive in
        /// the same order however the header was written. ModelRules.Apply runs
        /// set, then multiply, then add within one rule, and RulePlan preserves
        /// load order between rules, so a deterministic order here is what keeps
        /// two launches of the same config identical.</summary>
        private static readonly string[] ModelOrder =
        {
            ItemModel, TalentModel, EffectModel, MatrixEffectModel,
        };

        /// <summary>The two models a row can POINT AT and therefore share with
        /// another row of the same sheet. ItemModel and TalentModel are a row's
        /// own identity — two rows claiming one is an authoring fault the
        /// (model, id) registry refuses — but two items legitimately pointing at
        /// one effect row is the shipped state twice over. See Reconcile().</summary>
        private static readonly string[] PayloadModels = { EffectModel, MatrixEffectModel };

        /// <summary>True when this file is a lever sheet this class expands.
        /// Overlays.Load asks BEFORE it derives a table name from the filename:
        /// TableOf("consumables-medical.csv") takes the name up to the first dot
        /// and appends "Model" because it does not already end in one, yielding
        /// "consumables-medicalModel". That is NON-NULL, so it does not trip the
        /// null guard in LoadTable, and 18 rows would build rules against a
        /// table that does not exist. It does not fail loudly; its only symptom
        /// is an orphan warning long afterwards. Exactly the trap
        /// GearClasses.Owns, Cyberweapons.Owns and Implants.Owns exist for.</summary>
        internal static bool Owns(string fileName) =>
            fileName != null && Sheets.ContainsKey(fileName);

        private static Lever[] LeversFor(string fileName)
        {
            Lever[] levers;
            return Sheets.TryGetValue(fileName ?? "", out levers) ? levers : null;
        }

        // ---- the map self-check ----------------------------------------------
        //
        // The alias rule is the one thing in this file that cannot be checked by
        // a build and is not yet checked repo-side (see the LEVER MAP note), so
        // it is checked HERE, once per process, and the line says WHAT IT
        // CHECKED and WHAT IT COULD NOT. A silent pass and an instrument that
        // never ran would otherwise look the same (AGENTS.md section 3).
        //
        // WHAT IT CANNOT SEE, said rather than left blank: it compares the map
        // to ITSELF. It cannot tell whether a target column exists in the game
        // table, whether the sheet header still matches this map, or whether the
        // generator changed its mind about which table a name belongs to. Those
        // three belong repo-side, to scripts/consumables.py against the dump.

        private static bool mapVerified;

        private static void VerifyMap()
        {
            if (mapVerified) return;
            mapVerified = true;

            int total = 0, aliased = 0, plain = 0, problems = 0;
            foreach (var sheet in Sheets)
            {
                var seenColumn = new HashSet<string>(StringComparer.Ordinal);
                var seenTarget = new HashSet<string>(StringComparer.Ordinal);
                foreach (var lever in sheet.Value)
                {
                    total++;

                    if (!seenColumn.Add(lever.Column))
                    {
                        Plugin.Log.LogError($"Consumables: {sheet.Key} declares the column "
                            + $"'{lever.Column}' TWICE in its lever map. One header cell "
                            + "cannot write two targets and the second entry would never be "
                            + "reached. This is a defect in this file, not in the sheet.");
                        problems++;
                    }
                    if (!seenTarget.Add(lever.Model + " " + lever.Target))
                    {
                        Plugin.Log.LogError($"Consumables: {sheet.Key} declares the target "
                            + $"({lever.Model}, {lever.Target}) TWICE in its lever map, so "
                            + "two header cells would write one game column and the winner "
                            + "would be header order. This is a defect in this file.");
                        problems++;
                    }

                    if (lever.Model == MatrixEffectModel)
                    {
                        aliased++;
                        // Every MatrixEffectModel column is aliased, all of them
                        // and not only the two that collide.
                        if (lever.Column != MatrixAliasPrefix + lever.Target)
                        {
                            Plugin.Log.LogError($"Consumables: {sheet.Key} lever "
                                + $"'{lever.Column}' targets ({MatrixEffectModel}, "
                                + $"{lever.Target}) but is not the alias of it — a "
                                + $"{MatrixEffectModel} column must appear in the header as "
                                + $"'{MatrixAliasPrefix}{lever.Target}'. REFUSED as a map "
                                + "defect.");
                            problems++;
                        }
                        if (NotAliasSet.Contains(lever.Column))
                        {
                            Plugin.Log.LogError($"Consumables: {sheet.Key} carries "
                                + $"'{lever.Column}' as a {MatrixEffectModel} lever. It is "
                                + "NOT an alias: MatrixEffect and MatrixDuration are real "
                                + $"{TalentModel} columns and {MatrixKey} is an identity "
                                + "column. Stripping the prefix off one of these sends a "
                                + "talent lever to the wrong table. REFUSED as a map defect.");
                            problems++;
                        }
                    }
                    else
                    {
                        plain++;
                        // NEVER STRIPPED FOR A NON-MATRIX TARGET. This is the
                        // half that catches MatrixEffect -> Effect.
                        if (lever.Column != lever.Target)
                        {
                            Plugin.Log.LogError($"Consumables: {sheet.Key} lever "
                                + $"'{lever.Column}' targets ({lever.Model}, {lever.Target}) "
                                + "under a different name. Only a " + MatrixEffectModel
                                + " column is renamed between header and target on these "
                                + "sheets, and this one is not a " + MatrixEffectModel
                                + " column. REFUSED as a map defect.");
                            problems++;
                        }
                    }
                }
            }

            Plugin.Log.LogInfo($"Consumables: lever map self-check ran over {Sheets.Count} "
                + $"sheet(s) and {total} lever(s) — {aliased} aliased {MatrixEffectModel} "
                + $"column(s) whose '{MatrixAliasPrefix}' prefix is stripped to reach the "
                + $"game column, {plain} written under the header name unchanged, "
                + $"{problems} defect(s) found. WHAT THIS CANNOT SEE, said rather than left "
                + "blank: it compares this map to ITSELF. It does not know whether a target "
                + "column exists in the game table, whether the six sheet headers still "
                + "match this map, or whether the generator changed which table a name "
                + "belongs to. Those three are repo-side and belong to "
                + "scripts/consumables.py against the dump; there is no plugin-map scrape "
                + "on the consumables side yet, so today NOTHING compares this table to the "
                + "generator's.");
        }

        // ---- the (model, id) registry ---------------------------------------
        //
        // (table, id), NEVER id alone — see the header. Static rather than
        // per-file so that the six sheets cannot both claim one row: they are
        // separate slices with separate toggles, and a row named by two sheets
        // would be written twice in whatever order Directory.GetFiles returned.
        //
        // Reset at the head of each Overlays.Load walk by Reset(), so a second
        // load in one process (the test harness does this) does not inherit the
        // first walk's claims and refuse every row.
        private static readonly Dictionary<string, string> Claimed =
            new Dictionary<string, string>(StringComparer.Ordinal);

        private static string KeyOf(string model, long id) =>
            model + " " + id.ToString(CultureInfo.InvariantCulture);

        internal static void Reset() { Claimed.Clear(); }

        // ---- per-row state ----------------------------------------------------

        private sealed class Half
        {
            internal readonly Dictionary<string, JsonElement> Set =
                new Dictionary<string, JsonElement>(StringComparer.Ordinal);
            internal readonly Dictionary<string, JsonElement> Multiply =
                new Dictionary<string, JsonElement>(StringComparer.Ordinal);
            internal readonly Dictionary<string, JsonElement> Add =
                new Dictionary<string, JsonElement>(StringComparer.Ordinal);
            internal bool Any => Set.Count > 0 || Multiply.Count > 0 || Add.Count > 0;
        }

        private sealed class Parsed
        {
            internal int Line;
            internal string ItemName;
            internal long ItemId;

            /// <summary>Id per model, 0 meaning "this row reaches no row of that
            /// table". A blank cell and a literal 0 both land here as 0 and both
            /// are legitimate: consumables-devices.csv ships 7 blank EffectId
            /// cells of 12, consumables-grenades.csv 10 of 11, and
            /// consumables-matrix.csv 6 blank EffectId and 4 blank
            /// MatrixEffectId of 11 [measured, 2026-09-14]. No TalentModel row
            /// with id 0 exists, and neither effect table has one.</summary>
            internal readonly Dictionary<string, long> Ids =
                new Dictionary<string, long>(StringComparer.Ordinal);

            internal readonly Dictionary<string, Half> Halves =
                new Dictionary<string, Half>(StringComparer.Ordinal);

            /// <summary>Raw payload cell text by (model, column), for the
            /// divergence comparison. Raw rather than parsed, so "=0" and "0"
            /// are told apart the way a player typed them.</summary>
            internal readonly Dictionary<string, string> RawCells =
                new Dictionary<string, string>(StringComparer.Ordinal);

            internal long IdOf(string model)
            {
                long v;
                return Ids.TryGetValue(model, out v) ? v : 0L;
            }

            internal Half HalfOf(string model)
            {
                Half h;
                if (!Halves.TryGetValue(model, out h)) Halves[model] = h = new Half();
                return h;
            }

            internal bool HasHalf(string model)
            {
                Half h;
                return Halves.TryGetValue(model, out h) && h.Any;
            }
        }

        // ---- expansion -------------------------------------------------------

        /// <summary>Read one consumable sheet and hand every rule it produces to
        /// <paramref name="adopt"/>. Returns the number of RULES emitted, which
        /// is what Overlays.Load counts — one sheet row can produce four, three,
        /// two, one or none.</summary>
        internal static int Expand(string path, Action<Rule> adopt)
        {
            VerifyMap();

            var name = Path.GetFileName(path);
            var levers = LeversFor(name);
            if (levers == null)
            {
                // Unreachable through Overlays.Load, which asks Owns first. Said
                // rather than assumed: a future caller that skipped the question
                // would otherwise get a silent zero.
                Plugin.Log.LogError($"Consumables: Expand was called for '{name}', which is "
                    + "not one of the six sheets this class declares ("
                    + string.Join(", ", Sheets.Keys.OrderBy(k => k, StringComparer.Ordinal))
                    + "). NO rule is emitted. Nothing read the file: the caller asked the "
                    + "wrong expander.");
                return 0;
            }
            var leverByColumn = levers.ToDictionary(l => l.Column, l => l, StringComparer.Ordinal);

            string[] lines;
            try { lines = File.ReadAllLines(path); }
            catch (Exception e)
            {
                Plugin.Log.LogError($"Consumables: could not read {path}: {e.Message}. "
                    + "NO rule is emitted from this sheet. This is a refusal, not an empty "
                    + "answer: how many rows it holds is not known, because nothing read "
                    + "it. Do not read this as 'the sheet was blank'.");
                return 0;
            }
            if (lines.Length < 2)
            {
                Plugin.Log.LogWarning($"Consumables: {name} has {lines.Length} line(s); "
                    + "a header and at least one data row are needed. No rule emitted.");
                return 0;
            }

            var header = Overlays.SplitLine(lines[0], ',').Select(h => h.Trim()).ToArray();

            // REFUSED CONTROL COLUMNS, tested before anything is parsed. The
            // whole file is refused rather than the column ignored: a sheet
            // carrying a clone column was authored by something that believed
            // clones come out of here, and the rest of its rows are not more
            // trustworthy than that one.
            foreach (var h in header)
            {
                string why;
                if (!RefusedControl.TryGetValue(h, out why)) continue;
                Plugin.Log.LogError($"Consumables: {name} header carries the control "
                    + $"column '{h}', which this dialect REFUSES: {why} NO rule is "
                    + "emitted from this sheet at all.");
                return 0;
            }

            // THE MODELS THIS SHEET CAN REACH, derived from its own lever map
            // rather than listed. ItemModel is always among them — ItemTypeId is
            // the row's identity — and consumables-sploitkits.csv reaches only
            // that one. The key column of every model in the set must be in the
            // header, because a rule cannot select a row without one.
            var needed = new HashSet<string>(levers.Select(l => l.Model), StringComparer.Ordinal);
            needed.Add(ItemModel);
            var unreachable = ModelOrder.Where(m => !needed.Contains(m)).ToArray();

            var keyAt = new Dictionary<string, int>(StringComparer.Ordinal);
            var missingKeys = new List<string>();
            foreach (var model in ModelOrder)
            {
                if (!needed.Contains(model)) continue;
                var col = KeyColumnOf[model];
                var at = Array.IndexOf(header, col);
                if (at < 0) missingKeys.Add($"{col} (for {model})");
                keyAt[model] = at;
            }
            if (missingKeys.Count > 0)
            {
                Plugin.Log.LogError($"Consumables: {name} declares lever(s) for "
                    + $"{string.Join(", ", needed.OrderBy(m => Array.IndexOf(ModelOrder, m)))} "
                    + "but its header is missing the key column(s) "
                    + $"{string.Join(", ", missingKeys)} (header: "
                    + string.Join(", ", header) + "). A rule cannot select a row without "
                    + "its key, and one row is several rows in several tables, so NO rule "
                    + "is emitted from this sheet at all — not even the halves that could "
                    + "be built. Half a consumable is a configuration nobody authored.");
                return 0;
            }

            // A header column that is neither identity, a known lever nor a
            // control column is NAMED, once each. Silently ignoring it is how a
            // renamed lever becomes a column nobody writes.
            var ignoredColumns = new List<string>();
            foreach (var h in header)
            {
                if (h.Length == 0 || IdentitySet.Contains(h)) continue;
                if (leverByColumn.ContainsKey(h)) continue;
                if (h.StartsWith("_", StringComparison.Ordinal)) continue;
                ignoredColumns.Add(h);
                Plugin.Log.LogWarning($"Consumables: {name} header column '{h}' is not one "
                    + $"of the {levers.Length} levers this sheet declares and is not a "
                    + "control column; it is IGNORED and nothing writes it. If it begins "
                    + $"'{MatrixAliasPrefix}', check it against the alias rule: every "
                    + $"{MatrixEffectModel} payload column is aliased, but MatrixEffect, "
                    + $"MatrixDuration and {MatrixKey} are not aliases.");
            }
            // A lever this sheet declares and the header does not carry is the
            // same gap from the other side, and is just as invisible otherwise.
            var absentLevers = levers.Where(l => Array.IndexOf(header, l.Column) < 0)
                                     .Select(l => l.Column).ToList();
            foreach (var col in absentLevers)
                Plugin.Log.LogWarning($"Consumables: {name} — this class declares a lever "
                    + $"'{col}' that the file's header does not carry, so NOTHING CAN WRITE "
                    + "IT this launch. Either the sheet was regenerated against a different "
                    + "dump or the map in Consumables.cs is stale. Named rather than left "
                    + "as a lever that quietly never fires.");

            int rows = 0, refused = 0, cells = 0, blankRows = 0, nowhere = 0;
            var parsed = new List<Parsed>();
            var repointed = new Dictionary<string, List<long>>(StringComparer.Ordinal);

            for (int i = 1; i < lines.Length; i++)
            {
                if (string.IsNullOrWhiteSpace(lines[i])) continue;
                rows++;
                var c = Overlays.SplitLine(lines[i], ',');

                // ItemTypeId is REQUIRED on every row of every sheet: it is the
                // row's identity and the only key present on all six.
                long itemId;
                var itemAt = keyAt[ItemModel];
                if (itemAt >= c.Length
                    || !long.TryParse((c[itemAt] ?? "").Trim(), NumberStyles.Integer,
                                      CultureInfo.InvariantCulture, out itemId))
                {
                    Plugin.Log.LogWarning($"Consumables[{name}:{i + 1}]: {ItemKey}="
                        + $"'{(itemAt < c.Length ? c[itemAt] : "<short row>")}' is not an "
                        + "integer id. The WHOLE row is skipped, every half of it: a "
                        + "consumable whose item row cannot be named is a configuration "
                        + "nobody authored.");
                    refused++;
                    continue;
                }

                var p = new Parsed
                {
                    Line = i + 1,
                    ItemId = itemId,
                    ItemName = Array.IndexOf(header, "ItemName") >= 0
                               && Array.IndexOf(header, "ItemName") < c.Length
                               ? (c[Array.IndexOf(header, "ItemName")] ?? "").Trim()
                               : "",
                };
                p.Ids[ItemModel] = itemId;

                // THE OTHER THREE IDS ARE OPTIONAL PER ROW AND BLANK IS NOT
                // MALFORMED. A blank cell means this row reaches no row of that
                // table — 7 of 12 device rows have a blank EffectId, 10 of 11
                // grenade rows do, and 6 of 11 matrix rows have a blank EffectId
                // with 4 having a blank MatrixEffectId [measured, 2026-09-14].
                // A NON-BLANK cell that is not an integer is a different thing
                // and takes the whole row with it, the way Cyberweapons.cs and
                // Implants.cs do: emitting the item half from a row whose effect
                // id is unreadable would leave a consumable with a new price and
                // its old payload.
                bool badId = false;
                foreach (var model in ModelOrder)
                {
                    if (model == ItemModel || !needed.Contains(model)) continue;
                    var at = keyAt[model];
                    var raw = at < c.Length ? (c[at] ?? "").Trim() : "";
                    if (raw.Length == 0) { p.Ids[model] = 0L; continue; }
                    long id;
                    if (!long.TryParse(raw, NumberStyles.Integer,
                                       CultureInfo.InvariantCulture, out id))
                    {
                        Plugin.Log.LogWarning($"Consumables[{name}:{i + 1}]: item {itemId}, "
                            + $"{KeyColumnOf[model]}='{raw}' is neither blank nor an integer "
                            + "id. Blank would mean 'this row reaches no " + model + " row' "
                            + "and is allowed; this is malformed. The WHOLE row is skipped, "
                            + "every half of it: half a consumable is a configuration "
                            + "nobody authored.");
                        badId = true;
                        break;
                    }
                    p.Ids[model] = id;
                }
                if (badId) { refused++; continue; }

                for (int h = 0; h < header.Length && h < c.Length; h++)
                {
                    Lever lever;
                    if (!leverByColumn.TryGetValue(header[h], out lever)) continue;

                    var raw = (c[h] ?? "").Trim();
                    // Raw text kept for the shared-row comparison, for the
                    // payload models only — those are the ones two rows can
                    // point at. Kept before the parse so an unparseable cell is
                    // still visible as divergence.
                    if (lever.Model == EffectModel || lever.Model == MatrixEffectModel)
                        p.RawCells[lever.Model + " " + lever.Column] = raw;

                    bool ok;
                    var adj = MissionRewards.Adjust.Parse(c[h], out ok);
                    if (!ok)
                    {
                        // THREE-STATE. A cell like "90x" parses to "no
                        // operation" under a two-state reader and is
                        // indistinguishable from a blank — a tuning change that
                        // silently did not happen. Named with sheet, row and
                        // column.
                        Plugin.Log.LogWarning($"Consumables[{name}:{i + 1}]: item {itemId}, "
                            + $"column {lever.Column}: '{c[h]}' is not an adjustment — "
                            + "expected blank, =N, +N, -N or xN. The cell is ignored; the "
                            + "rest of the row still applies.");
                        refused++;
                        continue;
                    }
                    if (adj.Kind == MissionRewards.AdjustKind.None) continue;   // blank

                    var targetId = p.IdOf(lever.Model);
                    if (targetId == 0)
                    {
                        // NOWHERE TO WRITE IT. No TalentModel row with id 0
                        // exists and neither effect table has one, so writing
                        // this cell would need a row that does not exist and
                        // picking one would be an invention. The Implants.cs
                        // precedent for ImplantEffectId 0.
                        Plugin.Log.LogWarning($"Consumables[{name}:{i + 1}]: item {itemId} "
                            + $"has {KeyColumnOf[lever.Model]} blank or 0 — it reaches no "
                            + $"{lever.Model} row — so the cell {lever.Column}='{c[h]}' has "
                            + "nowhere to go and is REFUSED. It is not written anywhere and "
                            + "it is not silently dropped either: this line is the whole "
                            + "record of it.");
                        refused++;
                        nowhere++;
                        continue;
                    }

                    var half = p.HalfOf(lever.Model);
                    var el = Num(adj.Value);
                    switch (adj.Kind)
                    {
                        case MissionRewards.AdjustKind.Set:      half.Set[lever.Target] = el; break;
                        case MissionRewards.AdjustKind.Multiply: half.Multiply[lever.Target] = el; break;
                        case MissionRewards.AdjustKind.Add:      half.Add[lever.Target] = el; break;
                    }
                    cells++;

                    // A POINTER CELL IS A REPOINT, NOT AN EDIT OF WHAT IT POINTS
                    // AT — and here the sheet can do BOTH, which is the
                    // difference from Cyberweapons.cs. SelfEffect, TargetEffect
                    // and MatrixEffect are ordinary TalentModel levers that aim
                    // the talent at a different row; the payload cells on the
                    // same line write the row named by that line's EffectId /
                    // MatrixEffectId, which is the SHIPPED resolution and does
                    // not move when the pointer cell changes. The two read
                    // identically in a grid, so the distinction is said out loud.
                    if (lever.Model == TalentModel
                        && (lever.Target == "SelfEffect" || lever.Target == "TargetEffect"
                            || lever.Target == "MatrixEffect"))
                    {
                        var k = lever.Target + " " + adj.Value.ToString("0.###",
                            CultureInfo.InvariantCulture);
                        List<long> owners;
                        if (!repointed.TryGetValue(k, out owners))
                            repointed[k] = owners = new List<long>();
                        owners.Add(p.IdOf(TalentModel));
                        Plugin.Log.LogInfo($"Consumables[{name}:{i + 1}]: talent "
                            + $"{p.IdOf(TalentModel)} {lever.Target} is REPOINTED at "
                            + $"{adj.Value:0.###}. This changes which effect row the talent "
                            + "uses; it does not change what that row does, and it does NOT "
                            + "move where this line's payload cells are written — those are "
                            + $"keyed on the {EffectKey}/{MatrixKey} printed on the line, "
                            + "which is the shipped resolution.");
                    }
                }

                if (!ModelOrder.Any(m => p.HasHalf(m))) blankRows++;
                parsed.Add(p);
            }

            // ---- reconcile the payload halves that share a row ---------------
            //
            // Two of the six sheets ship this today:
            //   EffectModel 76005 <- consumables-medical.csv rows 6 and 19
            //   EffectModel 76017 <- consumables-devices.csv rows 4, 8 and 10
            // [measured, 2026-09-14]
            //
            // Reconciled HERE, before any rule is built, rather than by letting
            // the (model, id) registry reject whichever row arrived second: that
            // would make the surviving edit depend on row order, and it could
            // not name the other owners, which is what design.md section 11
            // requires the refusal to do.
            //
            // Identical payloads — including all-blank, which is today — are NOT
            // divergence. One rule is emitted and the sharing is marked.
            //
            // ItemModel and TalentModel are NOT reconciled here on purpose: they
            // are a row's own identity, not something a row points at, so two
            // rows claiming one is an authoring fault and the registry's refusal
            // is the right answer.
            var blocked = new HashSet<string>(StringComparer.Ordinal);
            int sharedMarks = 0;
            foreach (var model in PayloadModels)
            {
                if (!needed.Contains(model)) continue;
                var byId = new Dictionary<long, List<Parsed>>();
                foreach (var p in parsed)
                {
                    var id = p.IdOf(model);
                    if (id == 0) continue;
                    List<Parsed> l;
                    if (!byId.TryGetValue(id, out l)) byId[id] = l = new List<Parsed>();
                    l.Add(p);
                }
                var columns = levers.Where(lv => lv.Model == model)
                                    .Select(lv => lv.Column).ToArray();
                foreach (var kv in byId.OrderBy(k => k.Key))
                {
                    if (kv.Value.Count < 2) continue;
                    sharedMarks++;
                    var owners = string.Join(", ", kv.Value.Select(
                        p => $"{p.ItemId} {p.ItemName} (row {p.Line})"));
                    var divergent = columns.Where(col =>
                        kv.Value.Select(p =>
                            {
                                string v;
                                return p.RawCells.TryGetValue(model + " " + col, out v) ? v : "";
                            })
                            .Distinct(StringComparer.Ordinal).Count() > 1).ToList();
                    if (divergent.Count > 0)
                    {
                        blocked.Add(KeyOf(model, kv.Key));
                        Plugin.Log.LogError($"Consumables: {name} — {KeyColumnOf[model]} "
                            + $"{kv.Key} is SHARED by {kv.Value.Count} rows of this sheet "
                            + $"({owners}) and they DIVERGE on "
                            + $"{string.Join(", ", divergent)}. One {model} row cannot hold "
                            + $"two payloads, so NO {model} rule is emitted for {kv.Key} at "
                            + "all — neither owner's version wins. Splitting it is an "
                            + "explicit per-row _clone opt-in (design.md section 11) and "
                            + "nothing has opted in; _clone in this header refuses the whole "
                            + "file. The other halves of those rows still apply: they are "
                            + "different rows and do not collide.");
                        refused++;
                    }
                    else
                    {
                        Plugin.Log.LogInfo($"Consumables: {name} — {KeyColumnOf[model]} "
                            + $"{kv.Key} is SHARED by {kv.Value.Count} rows of this sheet "
                            + $"({owners}). All of them are editable, so the payload halves "
                            + "CAN diverge; they are identical here, so one rule is emitted "
                            + "and an edit to it reaches every owner. A divergent edit is "
                            + "refused and names them all.");
                    }
                }
            }

            // ---- build ------------------------------------------------------
            int emitted = 0;
            var perModel = ModelOrder.ToDictionary(m => m, m => 0, StringComparer.Ordinal);
            var emittedPayload = new HashSet<string>(StringComparer.Ordinal);

            foreach (var p in parsed)
            {
                foreach (var model in ModelOrder)
                {
                    if (!p.HasHalf(model)) continue;
                    var id = p.IdOf(model);
                    if (id == 0) continue;          // already refused cell by cell above
                    var key = KeyOf(model, id);

                    if (model == EffectModel || model == MatrixEffectModel)
                    {
                        if (blocked.Contains(key)) continue;
                        if (!emittedPayload.Add(key)) continue;   // identical, already emitted
                    }

                    string already;
                    if (Claimed.TryGetValue(key, out already))
                    {
                        Plugin.Log.LogWarning($"Consumables[{name}:{p.Line}]: ({model}, "
                            + $"{id}) is already written by {already}. One row, one key — "
                            + "two rows writing one key is load order, not a merge, so this "
                            + "one is REFUSED rather than applied second. Note the key is "
                            + $"(table, id): {TalentModel} 75022 is Bio-Stitch Bandages and "
                            + $"{EffectModel} 75022 is Mass Trauma Kit's effect, both rows "
                            + "of consumables-medical.csv, and this registry keeps them "
                            + "apart.");
                        refused++;
                        continue;
                    }
                    Claimed[key] = $"{name}:{p.Line}";

                    var half = p.HalfOf(model);
                    var keyColumn = KeyColumnOf[model];
                    adopt(new Rule
                    {
                        Model   = model,
                        Comment = $"{name} — {keyColumn} {id} (item {p.ItemId} "
                                + $"{p.ItemName}, talent {p.IdOf(TalentModel)}, effect "
                                + $"{p.IdOf(EffectModel)}, matrix effect "
                                + $"{p.IdOf(MatrixEffectModel)}; one sheet row split across "
                                + "up to four tables)",
                        Where   = new Dictionary<string, JsonElement> { { keyColumn, Num(id) } },
                        Set      = half.Set.Count > 0 ? half.Set : null,
                        Multiply = half.Multiply.Count > 0 ? half.Multiply : null,
                        Add      = half.Add.Count > 0 ? half.Add : null,
                    });
                    emitted++;
                    perModel[model] = perModel[model] + 1;
                }
            }

            // THE LOAD-TIME REPORT. Every number it can know, printed whether or
            // not it is zero, and a named statement of the ones it cannot.
            Plugin.Log.LogInfo($"Consumables: {name} — {rows} row(s), {emitted} rule(s) "
                + "emitted ("
                + string.Join(", ", ModelOrder.Select(m => $"{perModel[m]} {m}"))
                + $"), {cells} lever cell(s) set, {blankRows} row(s) with every cell blank, "
                + $"{refused} cell(s) or row(s) refused, {nowhere} of those refused for "
                + "having no row of their table to write to, "
                + $"{sharedMarks} payload row(s) shared by two or more rows of this sheet. "
                + $"{levers.Length} lever column(s) declared for this sheet, "
                + $"{header.Length} header column(s) read, {ignoredColumns.Count} header "
                + "column(s) ignored"
                + (ignoredColumns.Count > 0 ? " (" + string.Join(", ", ignoredColumns) + ")" : "")
                + $", {absentLevers.Count} declared lever(s) absent from the header"
                + (absentLevers.Count > 0 ? " (" + string.Join(", ", absentLevers) + ")" : "")
                + ".");

            // NAME WHAT IT SKIPPED, not only what it did. A sheet that reaches
            // three tables and a sheet that reaches one produce the same "0
            // rule(s)" line otherwise.
            if (unreachable.Length > 0)
                Plugin.Log.LogInfo($"Consumables: {name} declares levers for "
                    + string.Join(", ", ModelOrder.Where(m => needed.Contains(m)))
                    + " and for NO OTHER TABLE. "
                    + string.Join(", ", unreachable) + " "
                    + (unreachable.Length == 1 ? "is" : "are")
                    + " NOT reachable from this sheet and no cell in it can write "
                    + (unreachable.Length == 1 ? "that table" : "those tables")
                    + ". For consumables-sploitkits.csv that is the intended shape: all "
                    + "three of its rows are TalentId 0, no TalentModel row with id 0 "
                    + "exists, and a sheet that showed talent columns would give the player "
                    + "rows that do nothing.");

            if (repointed.Count > 0)
            {
                var collided = repointed.Where(k => k.Value.Count > 1).ToList();
                foreach (var kv in collided)
                    Plugin.Log.LogWarning($"Consumables: {name} repoints {kv.Value.Count} "
                        + $"talent(s) ({string.Join(", ", kv.Value)}) at the same {kv.Key}. "
                        + "They now SHARE that effect row: an edit to what it does reaches "
                        + "all of them. design.md section 11 makes splitting a shared row "
                        + "an explicit per-row opt-in and nothing here emits a clone.");
                Plugin.Log.LogInfo($"Consumables: {name} — {repointed.Count} distinct effect "
                    + $"pointer value(s) written by this sheet, {collided.Count} of them "
                    + "landing two or more talents on one row.");
            }

            // `refused == 0` is part of the condition, not decoration. Without
            // it this line would also fire on a file whose every cell was
            // REFUSED — unparseable text, or a payload cell on a row that
            // reaches no such row — and would then describe a file full of
            // rejected edits as a file full of blanks. Those two are opposite
            // findings and the summary above carries both counts either way.
            if (rows > 0 && blankRows == rows && refused == 0)
                Plugin.Log.LogInfo($"Consumables: {name} produced NO RULE AT ALL, and the "
                    + "file WAS READ: all "
                    + $"{rows} of its row(s) were parsed and every lever cell in every one "
                    + "of them was blank, which in this dialect means 'leave that column "
                    + "alone'. The rows are present with their shipped values in _comment "
                    + "and no override set. THIS IS NOT THE SAME ANSWER AS A FILE NOTHING "
                    + "READ: a read failure logs an Error above saying the row count is not "
                    + "known. The mod does not tune these today — 0 of the rules in "
                    + "ckf.hardmode.rules.json select any of the 194 consumable-reachable "
                    + "(table, id) pairs [measured] — and a shipped override would be a "
                    + "balance change (proposal.md non-goals).");

            Plugin.Log.LogInfo($"Consumables: {name} emits no clone and cannot. _clone and "
                + "_serveOn in a header refuse the whole file. WHAT THIS CANNOT SEE, said "
                + "rather than left blank: the sheet carries no shipped values — a blank "
                + "cell means 'leave that column alone' — so sharing that exists in the "
                + "SHIPPED data between a row of this sheet and a row NO SHEET SHOWS is "
                + "invisible here, and this line will not mention it. The shared rows this "
                + "walk CAN see are the ones whose owners are all inside this one file, and "
                + "they are counted above. The other half is owned repo-side by "
                + "scripts/consumables.py, which measures it from the dump, and by the "
                + "editor's cell marking.");

            return emitted;
        }

        private static JsonElement Num(double v) =>
            JsonDocument.Parse(v.ToString("R", CultureInfo.InvariantCulture)).RootElement.Clone();

        private static JsonElement Num(long v) =>
            JsonDocument.Parse(v.ToString(CultureInfo.InvariantCulture)).RootElement.Clone();
    }
}
