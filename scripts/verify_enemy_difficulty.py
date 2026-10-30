"""Verify on-disk Enemy Difficulty SQL against official data and live authoring.

The verifier never calls the export planner. It applies SQL only to an in-memory
copy, independently evaluates authored CSVs, and compares every resulting row.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from decimal import Decimal, ROUND_HALF_EVEN
import hashlib
import json
from pathlib import Path
import sqlite3

from static_data import StaticData, DEFAULT_DB, quote, integer_text
# Shared declarations, not planner results or evaluation functions.
from export_enemy_difficulty import (CONFIG, PROJECT, KEYS, SPAWN_TAGS, STAT_FLOORS,
                                     FAMILIES, EXISTING_TIERS, TALENT_ID_START,
                                     EFFECT_VARIANTS, EFFECT_ID_START)


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def verify(sql_path, data_path=DEFAULT_DB, config_dir=CONFIG):
    sql_bytes = sql_path.read_bytes()
    locale_path = sql_path.with_name("en-US.json")
    locale = json.loads(locale_path.read_bytes())
    counts = Counter()
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        with StaticData(data_path) as db:
            db.connection.backup(conn)
            before_raw = {t: db.connection.execute("SELECT * FROM " + quote(t)).fetchall() for t in db.schema}
            before_schema = db.connection.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name").fetchall()
            kinds = {t: {c[1]: c[2] for c in db.schema[t]} for t in KEYS}

            def normalize(t, row):
                result = {}
                for c, kind in kinds[t].items():
                    v = row[c]
                    if v is None:
                        result[c] = ""
                    elif "INT" in kind.upper() and isinstance(v, (float, int)):
                        result[c] = int(integer_text(v, t + "." + c))
                    else:
                        result[c] = v
                return result

            original = {t: {int(r[KEYS[t]]): normalize(t, r) for r in conn.execute("SELECT * FROM " + quote(t))} for t in KEYS}
            expected = {t: {i: dict(r) for i, r in rows.items()} for t, rows in original.items()}
            authored_ids, expected_names = set(), {}

            def evaluate_csv(t, filename):
                candidates = [p for p in (config_dir / filename, config_dir / (filename + ".disabled")) if p.is_file()]
                require(len(candidates) == 1, "Ambiguous source: " + filename)
                with candidates[0].open(encoding="utf-8-sig", newline="") as handle:
                    rows = list(csv.DictReader(handle))
                converted = []
                for raw in rows:
                    if not raw.get(KEYS[t], "").strip():
                        continue
                    identity = int(raw[KEYS[t]])
                    values = {}
                    for c, v in raw.items():
                        if c.startswith("_") or c == KEYS[t] or not v or not v.strip():
                            continue
                        require(c in kinds[t], "Unknown authored column: " + c)
                        if "INT" in kinds[t][c].upper():
                            values[c] = int(Decimal(v).to_integral_value(rounding=ROUND_HALF_EVEN))
                        elif kinds[t][c].upper() == "REAL":
                            values[c] = float(v)
                        else:
                            values[c] = v
                    converted.append((identity, raw.get("_clone", "").strip(), values, raw.get("_comment", "")))
                    if t == "MonsterType":
                        authored_ids.add(identity)
                for identity, source, values, _ in converted:
                    if not source:
                        require(identity in expected[t], f"Authored row missing: {t} {identity}")
                        expected[t][identity].update(values)
                for identity, source, values, comment in converted:
                    if source:
                        require(identity not in expected[t], f"Authored clone collision: {t} {identity}")
                        expected[t][identity] = {**expected[t][int(source)], **values, KEYS[t]: identity}
                        if t in ("Weapon", "Armor"):
                            stem = "WeaponName." if t == "Weapon" else "ArmorName."
                            family = comment.split(" tier PL ")[0].replace("-", " ").title()
                            label = db.locale.get(stem + source, family)
                            expected_names[stem + str(identity)] = f"{label} (PL {expected[t][identity]['PowerLevel']})"
                counts["authored_rows"] += len(converted)

            for t in ("Armor", "Weapon", "MonsterType"):
                evaluate_csv(t, t + "Model.csv")
            for tag in SPAWN_TAGS:
                evaluate_csv("MonsterGroupMember", f"MonsterGroupMemberModel.spawn-{tag}.csv")
            expected["Rule"][82]["Value"] = 20

            grouped = defaultdict(dict)
            for i, r in original["MonsterType"].items():
                grouped[r["PowerGroupId"]][r["PowerLevel"]] = r
            for pg, lv in grouped.items():
                if set(lv) != set(range(1, 21)) or any(r["MonsterTypeId"] in authored_ids for r in lv.values()):
                    continue
                for field in ("WeaponTypeId", "ArmorTypeId"):
                    sig = tuple(lv[p][field] for p in range(1, 11))
                    donors = [rows for rows in grouped.values() if set(rows) == set(range(1, 21))
                              and all(r["MonsterTypeId"] in authored_ids for r in rows.values())
                              and tuple(rows[p][field] for p in range(1, 11)) == sig]
                    tails = {tuple(expected["MonsterType"][rows[p]["MonsterTypeId"]][field] for p in range(11, 21)) for rows in donors}
                    require(len(tails) == 1, f"New gear family ambiguous: PG {pg} {field}")
                    for p, pointer in zip(range(11, 21), next(iter(tails))):
                        expected["MonsterType"][lv[p]["MonsterTypeId"]][field] = pointer
                        counts["new_ladder_gear_assignments"] += 1
            for pg, levels in grouped.items():
                floor = {}
                for pl, source in sorted(levels.items()):
                    row = expected["MonsterType"][source["MonsterTypeId"]]
                    for c in STAT_FLOORS:
                        floor[c] = max(floor.get(c, row[c]), row[c])
                        if pl >= 11:
                            row[c] = floor[c]

            next_id = TALENT_ID_START
            next_effect = EFFECT_ID_START
            expected_coverage = []
            for base_id, mid_id, high_id in FAMILIES:
                first, middle, last = (original["MonsterTalent"][i] for i in (base_id, mid_id, high_id))
                name = db.locale[f"MonsterTalent.Name.{base_id}"]
                for identity, variant in original["MonsterTalent"].items():
                    if (variant["MinPowerLevel"] != 0
                            or variant["MonsterTalentTypeId"] != first["MonsterTalentTypeId"]
                            or db.locale.get(f"MonsterTalent.Name.{identity}") != name):
                        continue
                    require(variant["TargetEffect"] == first["TargetEffect"] or EFFECT_VARIANTS.get(identity) == base_id,
                            f"Unmapped effect variant: {identity}")
                    ids = EXISTING_TIERS.get(identity)
                    if ids is None:
                        ids = next_id, next_id + 1
                        next_id += 2
                    expected["MonsterTalent"][identity]["MaxPowerLevel"] = middle["MinPowerLevel"] - 1
                    for tier_id, exemplar in zip(ids, (middle, last)):
                        changes = {"MinPowerLevel": exemplar["MinPowerLevel"], "MaxPowerLevel": exemplar["MaxPowerLevel"]}
                        for field in first:
                            if field in ("MonsterTalentId", "MonsterTalentGroup", "MinPowerLevel", "MaxPowerLevel"):
                                continue
                            if exemplar[field] == first[field]:
                                continue
                            if field == "TargetEffect" or not isinstance(first[field], (int, float)):
                                changes[field] = exemplar[field]
                            else:
                                changes[field] = variant[field] + exemplar[field] - first[field]
                        if identity in EFFECT_VARIANTS:
                            source_effect = original["Effect"][variant["TargetEffect"]]
                            first_effect = original["Effect"][first["TargetEffect"]]
                            tier_effect = original["Effect"][exemplar["TargetEffect"]]
                            copy = {**source_effect, "EffectId": next_effect}
                            for field in first_effect:
                                if field == "EffectId" or first_effect[field] == tier_effect[field]:
                                    continue
                                copy[field] = (source_effect[field] + tier_effect[field] - first_effect[field]
                                               if isinstance(first_effect[field], (int, float)) else tier_effect[field])
                            expected["Effect"][next_effect] = copy
                            expected_names[f"Effect.Name.{next_effect}"] = db.locale.get(f"Effect.Name.{variant['TargetEffect']}", name)
                            changes["TargetEffect"] = next_effect
                            next_effect += 1
                        if tier_id not in original["MonsterTalent"]:
                            expected["MonsterTalent"][tier_id] = {**variant, "MonsterTalentId": tier_id}
                            expected_names[f"MonsterTalent.Name.{tier_id}"] = name
                        expected["MonsterTalent"][tier_id].update(changes)
                    expected_coverage.append((identity, ids, middle["MinPowerLevel"], last["MinPowerLevel"]))

            conn.executescript(sql_bytes.decode("utf-8-sig"))
            actual_schema = [tuple(r) for r in conn.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name")]
            require(actual_schema == before_schema, "SQL schema changed")
            actual = {t: {int(r[KEYS[t]]): normalize(t, r) for r in conn.execute("SELECT * FROM " + quote(t))} for t in KEYS}
            for t, rows in expected.items():
                require(set(actual[t]) == set(rows), f"Row identities differ: {t}")
                for identity, expected_row in rows.items():
                    differences = {c: (v, actual[t][identity][c]) for c, v in expected_row.items() if v != actual[t][identity][c]}
                    require(not differences, f"Row mismatch: {t} {identity}: {differences}")
                    counts["exact_owned_rows"] += 1
            for t in db.schema:
                if t not in KEYS:
                    current = [tuple(r) for r in conn.execute("SELECT * FROM " + quote(t))]
                    require(current == before_raw[t], "Unowned table changed: " + t)
                    counts["unchanged_tables"] += 1
            require(locale == expected_names, "Locale entries do not match inserted rows")
            counts["localized_inserted_rows"] = len(locale)
            effect_ids = set(actual["Effect"])
            for row in actual["MonsterType"].values():
                if row["PowerLevel"] >= 11:
                    for column, t in (("WeaponTypeId", "Weapon"), ("ArmorTypeId", "Armor")):
                        require(row[column] in actual[t], f"Unresolved high-PL {column}: {row['MonsterTypeId']}")
                        counts["high_PL_gear_references"] += 1
            for row in actual["MonsterTalent"].values():
                require(not row["TargetEffect"] or row["TargetEffect"] in effect_ids,
                        f"Unresolved talent effect: {row['MonsterTalentId']}")
            for identity, ids, middle_start, high_start in expected_coverage:
                for pl in range(1, 21):
                    ids_to_check = (identity,) + ids
                    eligible = [i for i in ids_to_check if actual["MonsterTalent"][i]["MinPowerLevel"] <= pl
                                and (not actual["MonsterTalent"][i]["MaxPowerLevel"]
                                     or actual["MonsterTalent"][i]["MaxPowerLevel"] >= pl)]
                    target = identity if pl < middle_start else ids[0] if pl < high_start else ids[1]
                    require(eligible == [target], f"Talent band gap/overlap: base {identity} PL {pl}: {eligible}")
                    counts["talent_band_checks"] += 1

            # Verify the weighted pool at each PL, not just the clone rows.
            roster_groups = {r["MonsterGroupId"] for r in actual["MonsterGroupMember"].values()
                             if r["MonsterGroupMemberId"] not in original["MonsterGroupMember"]}
            for group in roster_groups:
                for pl in range(1, 21):
                    def pool(rows):
                        result = Counter()
                        for r in rows.values():
                            if r["MonsterGroupId"] == group and r["MinPowerLevel"] <= pl and (not r["MaxPowerLevel"] or pl <= r["MaxPowerLevel"]):
                                key = tuple(r[c] for c in ("MonsterType", "Slot", "Faction", "MinSecLevel", "MaxSecLevel", "Exclusive"))
                                result[key] += r["WeightedRoll"]
                        return result
                    require(pool(actual["MonsterGroupMember"]) == pool(expected["MonsterGroupMember"]),
                            f"Roster weight mismatch: group {group} PL {pl}")
                    counts["roster_PL_checks"] += 1

            first_apply = {t: [tuple(r) for r in conn.execute("SELECT * FROM " + quote(t))] for t in db.schema}
            conn.executescript(sql_bytes.decode("utf-8-sig"))
            for t in db.schema:
                require([tuple(r) for r in conn.execute("SELECT * FROM " + quote(t))] == first_apply[t],
                        "Repeated SQL application accumulates changes: " + t)
            counts["repeat_application_tables"] = len(db.schema)
            db.assert_unchanged()
        return {"status": "PASS", "sql_sha256": hashlib.sha256(sql_bytes).hexdigest(),
                "checks": dict(counts), "talent_variants": len(expected_coverage),
                "native_runtime": "NOT RUN: in-game Workshop activation remains to be tested"}
    finally:
        conn.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sql", type=Path, default=PROJECT / "prepared/_data/data.sql")
    p.add_argument("--data", type=Path, default=DEFAULT_DB)
    p.add_argument("--config-dir", type=Path, default=CONFIG)
    p.add_argument("--report", type=Path)
    args = p.parse_args()
    result = verify(args.sql, args.data, args.config_dir)
    if args.report:
        from export_enemy_difficulty import guarded_write, encode
        guarded_write(args.report, encode(result))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
