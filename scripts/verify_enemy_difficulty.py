"""Independently verify armor-only SQL against official and authored data.

Every official table is compared. Only Armor rows, MonsterType.ArmorTypeId and Rule82.Value=20
may change; SQL write attempts outside that scope are rejected even if no-op.
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
from export_enemy_difficulty import CONFIG, PROJECT


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def verify(sql_path, data_path=DEFAULT_DB, config_dir=CONFIG, native_integrity=False):
    sql_bytes = sql_path.read_bytes()
    locale = json.loads(sql_path.with_name("en-US.json").read_bytes())
    conn = sqlite3.connect(":memory:")
    counts = Counter()
    try:
        with StaticData(data_path) as db:
            db.connection.backup(conn)
            schema = db.connection.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name").fetchall()
            keys = {t: [c[1] for c in declaration if c[5]] for t, declaration in db.schema.items()}

            def raw_rows(t):
                order = " ORDER BY " + ",".join(map(quote, keys[t])) if keys[t] else ""
                return conn.execute("SELECT * FROM " + quote(t) + order).fetchall()

            before = {t: raw_rows(t) for t in db.schema}
            kinds = {t: {c[1]: c[2] for c in db.schema[t]} for t in ("Armor", "MonsterType", "Rule")}

            def normalize(t, rows):
                columns = list(kinds[t])
                result = {}
                for row in rows:
                    values = {}
                    for column, value in zip(columns, row):
                        if value is None:
                            value = ""
                        elif "INT" in kinds[t][column].upper() and isinstance(value, (int, float)):
                            value = int(integer_text(value, t + "." + column))
                        values[column] = value
                    result[values[keys[t][0]]] = values
                return result

            original = {t: normalize(t, before[t]) for t in kinds}
            target = {t: {i: dict(r) for i, r in rows.items()} for t, rows in original.items()}
            authored, expected_names = set(), {}
            for t in ("Armor", "MonsterType"):
                filename = t + "Model.csv"
                paths = [p for p in (config_dir / filename, config_dir / (filename + ".disabled")) if p.is_file()]
                require(len(paths) == 1, "Ambiguous source: " + filename)
                with paths[0].open(encoding="utf-8-sig", newline="") as handle:
                    rows = list(csv.DictReader(handle))
                converted, seen = [], set()
                for raw in rows:
                    if not raw.get(keys[t][0], "").strip():
                        continue
                    identity = int(raw[keys[t][0]])
                    require(identity not in seen, f"Duplicate authored row: {t} {identity}")
                    seen.add(identity)
                    changes = {}
                    for c, value in raw.items():
                        if c.startswith("_") or c == keys[t][0] or not value or not value.strip():
                            continue
                        if t == "MonsterType" and c != "ArmorTypeId":
                            continue
                        require(c in kinds[t], "Unknown authored column: " + c)
                        if "INT" in kinds[t][c].upper():
                            changes[c] = int(Decimal(value).to_integral_value(rounding=ROUND_HALF_EVEN))
                        elif kinds[t][c].upper() == "REAL":
                            changes[c] = float(value)
                        else:
                            changes[c] = value
                    source = raw.get("_clone", "").strip()
                    require(t == "Armor" or not source, "MonsterType clone outside armor scope")
                    converted.append((identity, source, changes, raw.get("_comment", "")))
                    if t == "MonsterType":
                        authored.add(identity)
                for identity, source, changes, _ in converted:
                    if not source:
                        require(identity in target[t], f"Authored row missing: {t} {identity}")
                        target[t][identity].update(changes)
                for identity, source, changes, comment in converted:
                    if source:
                        require(identity not in target[t], f"Authored clone collision: {t} {identity}")
                        require(int(source) in target[t], f"Authored clone source missing: {t} {source}")
                        target[t][identity] = {**target[t][int(source)], **changes, keys[t][0]: identity}
                        family = comment.split(" tier PL ")[0].replace("-", " ").title()
                        label = db.locale.get("ArmorName." + source, family)
                        expected_names["ArmorName." + str(identity)] = f"{label} (PL {target[t][identity]['PowerLevel']})"
                counts["authored_rows"] += len(converted)

            require(target["Rule"][82]["ConfigName"] == "Max Enemy Power Level", "Rule82 declaration changed")
            target["Rule"][82]["Value"] = 20
            groups, ambiguous = defaultdict(dict), set()
            for row in original["MonsterType"].values():
                pg, pl = row["PowerGroupId"], row["PowerLevel"]
                if pl in groups[pg]:
                    ambiguous.add(pg)
                groups[pg][pl] = row
            for pg, levels in groups.items():
                if set(levels) != set(range(1, 21)) or any(r["MonsterTypeId"] in authored for r in levels.values()):
                    continue
                require(pg not in ambiguous, f"Ambiguous full armor ladder: {pg}")
                signature = tuple(levels[p]["ArmorTypeId"] for p in range(1, 11))
                donors = [g for identity, g in groups.items() if identity not in ambiguous and set(g) == set(range(1, 21))
                          and all(r["MonsterTypeId"] in authored for r in g.values())
                          and tuple(g[p]["ArmorTypeId"] for p in range(1, 11)) == signature]
                tails = {tuple(target["MonsterType"][g[p]["MonsterTypeId"]]["ArmorTypeId"] for p in range(11, 21)) for g in donors}
                require(len(tails) == 1, f"New armor family ambiguous: PG {pg}")
                for p, pointer in zip(range(11, 21), next(iter(tails))):
                    target["MonsterType"][levels[p]["MonsterTypeId"]]["ArmorTypeId"] = pointer
                    counts["new_ladder_armor_assignments"] += 1

            denied = []

            def authorizer(action, table, column, _db, _trigger):
                if action == sqlite3.SQLITE_UPDATE:
                    allowed = ((table == "Armor" and column != "ArmorId")
                               or (table == "MonsterType" and column == "ArmorTypeId")
                               or (table == "Rule" and column == "Value"))
                elif action == sqlite3.SQLITE_INSERT:
                    allowed = table == "Armor"
                elif action in (sqlite3.SQLITE_DELETE, sqlite3.SQLITE_CREATE_TABLE,
                                sqlite3.SQLITE_DROP_TABLE, sqlite3.SQLITE_ALTER_TABLE,
                                sqlite3.SQLITE_CREATE_TRIGGER, sqlite3.SQLITE_DROP_TRIGGER,
                                sqlite3.SQLITE_CREATE_INDEX, sqlite3.SQLITE_DROP_INDEX,
                                sqlite3.SQLITE_CREATE_VIEW, sqlite3.SQLITE_DROP_VIEW):
                    allowed = False
                else:
                    return sqlite3.SQLITE_OK
                if not allowed:
                    denied.append(f"{table}.{column}" if column else table)
                return sqlite3.SQLITE_OK if allowed else sqlite3.SQLITE_DENY

            def apply():
                conn.set_authorizer(authorizer)
                try:
                    conn.executescript(sql_bytes.decode("utf-8-sig"))
                except sqlite3.DatabaseError as exc:
                    if denied:
                        raise AssertionError("Forbidden SQL write: " + denied[0]) from exc
                    raise
                finally:
                    conn.set_authorizer(None)

            apply()
            require(conn.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name").fetchall() == schema,
                    "SQL schema changed")
            actual = {t: normalize(t, raw_rows(t)) for t in kinds}
            for t, rows in target.items():
                require(set(actual[t]) == set(rows), "Row identities differ: " + t)
                for identity, expected_row in rows.items():
                    differences = {c: (value, actual[t][identity][c]) for c, value in expected_row.items()
                                   if value != actual[t][identity][c]}
                    require(not differences, f"Row mismatch: {t} {identity}: {differences}")
                    counts["exact_owned_rows"] += 1
            for t in db.schema:
                if t not in kinds:
                    require(raw_rows(t) == before[t], "Unowned table changed: " + t)
                    counts["unchanged_tables"] += 1
            require(locale == expected_names, "Locale entries do not match inserted armors")
            for identity, row in actual["MonsterType"].items():
                if row["ArmorTypeId"] != original["MonsterType"][identity]["ArmorTypeId"]:
                    require(row["ArmorTypeId"] in actual["Armor"], f"Unresolved authored armor: {identity}")
                    counts["authored_armor_references"] += 1
            # Native content can contain unresolved references that this package
            # does not own. Keep the old global checks runnable by name.
            native_checks = {
                "native_high_PL_gear_resolution": "NOT RUN: opt in with --native-integrity; authored armor resolution ran",
                "native_talent_effect_resolution": "NOT RUN: opt in with --native-integrity; native talent rows were compared unchanged",
            }
            if native_integrity:
                weapon_ids = {r[0] for r in conn.execute("SELECT WeaponId FROM Weapon")}
                effect_ids = {r[0] for r in conn.execute("SELECT EffectId FROM Effect")}
                for row in actual["MonsterType"].values():
                    if row["PowerLevel"] >= 11:
                        require(row["WeaponTypeId"] in weapon_ids,
                                f"Unresolved high-PL WeaponTypeId: {row['MonsterTypeId']}")
                        require(row["ArmorTypeId"] in actual["Armor"],
                                f"Unresolved high-PL ArmorTypeId: {row['MonsterTypeId']}")
                for identity, effect in conn.execute("SELECT MonsterTalentId,TargetEffect FROM MonsterTalent"):
                    require(not effect or effect in effect_ids, f"Unresolved talent effect: {identity}")
                native_checks = {name: "PASS" for name in native_checks}
            first = {t: raw_rows(t) for t in db.schema}
            apply()
            for t in db.schema:
                require(raw_rows(t) == first[t], "Repeated SQL application accumulates changes: " + t)
            counts["repeat_application_tables"] = len(db.schema)
            counts["localized_inserted_armors"] = len(locale)
            db.assert_unchanged()
        return {"status": "PASS", "scope": "Armor rows, MonsterType.ArmorTypeId and Rule82.Value=20",
                "sql_sha256": hashlib.sha256(sql_bytes).hexdigest(), "checks": dict(counts),
                "native_integrity_checks": native_checks,
                "native_runtime": "NOT RUN: armor-only Workshop activation remains to be tested"}
    finally:
        conn.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sql", type=Path, default=PROJECT / "prepared/_data/data.sql")
    p.add_argument("--data", type=Path, default=DEFAULT_DB)
    p.add_argument("--config-dir", type=Path, default=CONFIG)
    p.add_argument("--report", type=Path)
    p.add_argument("--native-integrity", action="store_true",
                   help="also run global native gear/effect resolution checks")
    args = p.parse_args()
    result = verify(args.sql, args.data, args.config_dir, args.native_integrity)
    if args.report:
        from export_enemy_difficulty import guarded_write, encode
        guarded_write(args.report, encode(result))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
