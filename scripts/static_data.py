"""Read the developer's content database without changing it or live tuning.

Model names are the mod's names; SQL names and numeric storage are translated
here. Explicit CSV directories remain usable for historical captures/fixtures.
They are never an automatic fallback for a missing or unreadable database.
"""
from __future__ import annotations

import argparse
import csv
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

ROOT = (Path(sys.executable).resolve().parent if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parents[1])
DEFAULT_DB = ROOT / 'Official' / 'data.db'
DEFAULT_PROBES = ROOT / 'sheets' / 'raw'

# The runtime still uses Drone* names for these two SQL Pet* tables.
TABLE_NAMES = {'DroneChassisModel': 'PetChassis',
               'DronePrebuiltModel': 'PetPrebuilt'}
COLUMN_NAMES = {
    'PetChassis': {'PetChassisType': 'DroneChassisType', 'PetClass': 'DroneClass'},
    'PetPrebuilt': {'PetPrebuiltType': 'DroneType', 'PetChassisId': 'DroneChassisId'},
    'CharacterLevel': {'job': 'Job', 'level': 'Level', 'levelType': 'LevelType',
                       'skill': 'Skill', 'talent': 'Talent', 'xp': 'Xp'},
    'Cosmetic': {'blendshape%d' % i: 'Blendshape%d' % i for i in range(1, 7)},
    'CosmeticAdjustment': {'blendshape%d' % i: 'Blendshape%d' % i for i in range(1, 7)},
}

# Presentation joins, not additional database columns. Untranslated keys remain
# visible as keys. Do not manufacture session state or computed combat stats.
LABELS = {
    'Weapon': {'WeaponName': 'WeaponName.{WeaponId}'},
    'WeaponMod': {'ModName': 'WeaponModName.{WeaponModId}'},
    'Armor': {'ArmorName': 'ArmorName.{ArmorId}'},
    'Item': {'ItemName': 'Item.Name.{ItemTypeId}', 'ItemDesc': 'Item.Desc.{ItemTypeId}'},
    'Implant': {'ImplantName': 'Implant.Name.{ImplantTypeId}',
                'ImplantDesc': 'Implant.Desc.{ImplantTypeId}'},
    'Job': {'JobName': 'Job.Name.{JobId}.Male'},
    'JobNode': {'JobNodeName': 'JobNode.Name.{JobNodeId}'},
    'Talent': {'TalentName': 'Talent.Name.{TalentId}'},
    'Effect': {'EffectName': 'Effect.Name.{EffectId}'},
    'MatrixEffect': {'EffectName': 'MatrixEffect.Name.{MatrixEffectId}'},
    'MonsterType': {'MonsterName': 'Monster.Name.{PowerGroupId}'},
    'Faction': {'FactionName': 'Faction.Name.{FactionId}'},
    'Cyberdeck': {'DeckName': 'Cyberdeck.Name.{CyberdeckId}'},
    'CyberdeckProgram': {'ProgramTitle': 'Program.Name.{CyberdeckProgramId}'},
    'MatrixIC': {'IcName': 'MatrixIC.Name.{IcTypeId}'},
    'MatrixFile': {'FileName': 'MatrixFile.Name.{MatrixFileId}'},
    'MatrixFileSet': {'FileSetName': 'MatrixFileSet.Name.{MatrixFileSetId}'},
    'Gear': {'GearName': 'Gear.Name.{GearTypeId}'},
    'Trait': {'TraitName': 'Trait.Name.{TraitId}_Male'},
    'SafehouseModule': {'ModuleName': 'SafehouseModule.Name.{ModuleTypeId}'},
}
WEAPON_CLASSES = {1: 'Blade', 2: 'Pistol', 3: 'AssaultRifle', 4: 'Shotgun',
                  5: 'EnergyRifle', 6: 'Sniper', 7: 'DogWeapon', 9: 'DroneAR',
                  10: 'SMG', 11: 'Revolver', 12: 'Bullpup', 14: 'Railgun',
                  16: 'CyberWeaponClaws', 17: 'CyberWeaponEyes', 18: 'DroneSMG',
                  19: 'DroneERifle'}

# Already declared runtime/presentation properties in consumables.py. These
# cannot be measured from SQL. Keep them separate from physical columns so a
# typo in a static column still fails the declaration checks.
MODEL_ONLY_COLUMNS = {
    'ItemModel': {'IsRowCurrentlySelected'},
    'TalentModel': {'TalentDesc', 'ManualTalentName', 'IsActiveForDisplay',
        'TalentCyberEnabled', 'AdjustedAp', 'AdjustedApMatrix', 'AdjustedCount',
        'AdjustedDamageBonus', 'AdjustedHealingBonus', 'AdjustedMatrixDuration',
        'AdjustedMaxCharges', 'AdjustedRange', 'AdjustedRangeAoE',
        'AdjustedSelfDuration', 'AdjustedTargetEffectDuration', 'AdjustedTokenDuration',
        'AdjustedTurnMaxUses', 'AllowsLessAp', 'AttackTalentStartingAP',
        'AttackTalentStartingAPCheck', 'DroneRuleType', 'TeamGlobal', 'TokenCancel'},
    'EffectModel': {'ManualEffectName', 'OwnerEntityId', 'isInit', 'effectsSet',
                   'HasInitSpecialCode', 'CritRateStreakSum'},
    'MatrixEffectModel': {'ManualEffectName', 'isInit', 'effectsSet', 'HasInitSpecialCode'},
}


class DataError(ValueError):
    """A named source, schema, or value could not be read completely."""


def add_argument(parser):
    parser.add_argument('--data', '--dump', dest='dump', default=str(DEFAULT_DB),
        help='static data.db (default Official/data.db); --dump is a legacy alias; '
             'an explicit historical CSV directory is also accepted')


def database_path(source=None):
    path = Path(DEFAULT_DB if source is None else source).resolve()
    if path.is_dir() and (path / 'data.db').is_file():
        path /= 'data.db'
    return path


def is_database(source=None):
    return database_path(source).suffix.lower() == '.db'


def sql_name(model):
    return TABLE_NAMES.get(model, model.removesuffix('Model'))


def model_name(table):
    reverse = {v: k for k, v in TABLE_NAMES.items()}
    return reverse.get(table, table + 'Model')


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def _stamp(path):
    s = path.stat()
    return s.st_mtime_ns, s.st_ctime_ns, s.st_size, s.st_ino


def integer_text(value, where):
    """Match the captured integer models: nearest integer, ties to even.

    SQLite INTEGER affinity also permits REAL storage. int(value) truncates
    those values and disagrees with the captured models. Keys must already be
    integral; callers enforce that separately rather than rounding identities.
    """
    try:
        n = Decimal(str(value))
        if not n.is_finite():
            raise ValueError('non-finite number')
        return str(int(n.to_integral_value(rounding=ROUND_HALF_EVEN)))
    except (InvalidOperation, ValueError) as exc:
        raise DataError('%s: invalid integer value %r' % (where, value)) from exc


class StaticData:
    """One read transaction, with replacement detection and no global cache."""
    def __init__(self, source=None, locale=None):
        self.path = database_path(source)
        self.database = is_database(self.path)
        self.locale_path = Path(locale).resolve() if locale else self.path.parent / 'en-US.json'
        self.connection = None
        self.stamps = {}
        self.locale = {}
        self.schema = {}
        self._tables = {}  # This transaction only; never shared across reloads.

    def __enter__(self):
        if self.connection is not None:
            raise DataError('StaticData already has an open transaction: %s' % self.path)
        self.stamps.clear()
        self.schema.clear()
        self.locale.clear()
        self._tables.clear()
        if not self.path.exists():
            raise DataError('Static source is missing: %s. Replace/download Official/data.db; '
                            'no CSV fallback was used.' % self.path)
        if not self.database:
            if not self.path.is_dir():
                raise DataError('Expected a content .db or an explicit CSV directory: %s' % self.path)
            return self
        self.stamps[self.path] = _stamp(self.path)
        try:
            # mode=ro refuses a missing file instead of creating an empty DB.
            self.connection = sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True)
            self.connection.execute('PRAGMA query_only=ON')
            self.connection.execute('BEGIN')
            for (name,) in self.connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
                self.schema[name] = list(self.connection.execute('PRAGMA table_info(%s)' % quote(name)))
            if not self.schema:
                raise DataError('No content tables in %s' % self.path)
            if self.locale_path.is_file():
                self.stamps[self.locale_path] = _stamp(self.locale_path)
                self.locale = json.loads(self.locale_path.read_text(encoding='utf-8-sig'))
                if not isinstance(self.locale, dict):
                    raise DataError('Locale must be an object: %s' % self.locale_path)
            self.assert_unchanged()
        except (sqlite3.Error, OSError, ValueError) as exc:
            if self.connection:
                self.connection.close()
                self.connection = None
            raise DataError('Cannot read static source %s: %s' % (self.path, exc)) from exc
        return self

    def assert_unchanged(self):
        for path, expected in self.stamps.items():
            if not path.exists() or _stamp(path) != expected:
                raise DataError('%s was replaced/changed while being read; retry with the new file.' % path)

    def __exit__(self, typ, value, traceback):
        try:
            if typ is None:
                self.assert_unchanged()
        finally:
            if self.connection:
                self.connection.close()
                self.connection = None
            self._tables.clear()

    def tables(self):
        if self.database:
            return [model_name(t) for t in self.schema]
        return [p.stem for p in sorted(self.path.glob('*.csv'))
                if not p.name.startswith('_') and not p.stem.startswith(('Game', 'Core'))]

    def read(self, model, required=(), raw=False, labels=True):
        if model.startswith(('Game', 'Core', '_')):
            raise DataError('%s is runtime information; read its probe/campaign capture explicitly.' % model)
        cache_key = model, raw, labels
        if self.database and self.connection is None:
            raise DataError('Read %s inside an open StaticData context.' % model)
        if cache_key in self._tables:
            cols, rows = self._tables[cache_key]
            missing = sorted(set(required) - set(cols))
            if missing:
                raise DataError('%s: %s is missing required column(s): %s' %
                                (self.path, model, ', '.join(missing)))
            return list(cols), [dict(r) for r in rows]
        if not self.database:
            path = self.path / (model + '.csv')
            try:
                with path.open(encoding='utf-8-sig', newline='') as f:
                    reader = csv.DictReader(f)
                    cols, rows = reader.fieldnames or [], list(reader)
            except OSError as exc:
                raise DataError('Cannot read %s: %s' % (path, exc)) from exc
        else:
            table = sql_name(model)
            if table not in self.schema:
                raise DataError('%s: missing table %s (requested as %s)' % (self.path, table, model))
            declaration = self.schema[table]
            aliases = COLUMN_NAMES.get(table, {})
            cols = [aliases.get(c[1], c[1]) for c in declaration]
            if len(set(cols)) != len(cols):
                raise DataError('%s: mapped column collision in %s' % (self.path, table))
            keys = [c[1] for c in declaration if c[5]]
            order = ' ORDER BY ' + ','.join(map(quote, keys)) if keys else ''
            rows = []
            seen = set()
            try:
                for values in self.connection.execute('SELECT * FROM %s%s' % (quote(table), order)):
                    row = {}
                    for col, spec, value in zip(cols, declaration, values):
                        where = '%s.%s row %d' % (table, spec[1], len(rows) + 1)
                        if spec[5]:
                            if value is None or (isinstance(value, float) and not value.is_integer()):
                                raise DataError('%s: null/non-integral primary key %r' % (where, value))
                        if value is None:
                            text = ''
                        elif not raw and 'INT' in spec[2].upper() and isinstance(value, (int, float)):
                            text = integer_text(value, where)
                        else:
                            text = str(value)
                        row[col] = text
                    identity = tuple(row[aliases.get(k, k)] for k in keys)
                    if keys and identity in seen:
                        raise DataError('%s: duplicate key %s' % (table, identity))
                    seen.add(identity)
                    if labels:
                        for col, template in LABELS.get(table, {}).items():
                            key = template.format_map(row)
                            value = self.locale.get(key, key)
                            row.setdefault(col, value if isinstance(value, str) else key)
                        if table == 'Weapon':
                            cls = int(row['WeaponClass'])
                            key = 'Gear.WeaponClass.' + WEAPON_CLASSES.get(cls, str(cls))
                            row['WeaponClassName'] = self.locale.get(key, key)
                    rows.append(row)
            except (sqlite3.Error, KeyError) as exc:
                raise DataError('%s: cannot completely read %s: %s' % (self.path, table, exc)) from exc
            if labels:
                cols += [c for c in LABELS.get(table, {}) if c not in cols]
                if table == 'Weapon' and 'WeaponClassName' not in cols:
                    cols.append('WeaponClassName')
        missing = sorted(set(required) - set(cols))
        if missing:
            raise DataError('%s: %s is missing required column(s): %s' %
                            (self.path, model, ', '.join(missing)))
        if self.database:
            self._tables[cache_key] = list(cols), rows
            return list(cols), [dict(r) for r in rows]
        return cols, rows


def read_table(source, model, required=(), **kwargs):
    with StaticData(source) as data:
        return data.read(model, required, **kwargs)


def read_rows(source, model, required=(), **kwargs):
    return read_table(source, model, required, **kwargs)[1]


def read_csv(path):
    """Read an actual CSV, or the legacy source/Model.csv call convention."""
    path = Path(path)
    if path.parent.suffix.lower() == '.db':
        return read_rows(path.parent, path.stem)
    try:
        with path.open(encoding='utf-8-sig', newline='') as f:
            return list(csv.DictReader(f))
    except FileNotFoundError:
        if is_database(path.parent):
            return read_rows(path.parent, path.stem)
        raise


def check(source=None):
    """Check the replacement itself and consumers' declared static targets."""
    # Imported only by the CLI, avoiding a reader/consumer import cycle.
    import gear_classes, cyberweapons, implants, consumables
    required = {
        'MonsterTypeModel': {'MonsterTypeId', 'PowerGroupId', 'PowerLevel', 'WeaponTypeId', 'ArmorTypeId'},
        'MonsterGroupModel': {'MonsterGroupId', 'FactionId', 'FactionClass'},
        'MonsterGroupMemberModel': {'MonsterGroupMemberId', 'MonsterGroupId', 'MonsterType', 'Slot',
                                  'MinPowerLevel', 'MaxPowerLevel', 'WeightedRoll'},
        'FactionModel': {'FactionId', 'ProcGenSelect'},
        'RuleModel': {'RuleId', 'Value', 'ConfigName', 'ConfigDesc'},
        'JobModel': {'JobId'}, 'JobNodeModel': {'JobNodeId', 'JobId', 'SubTree', 'NodeTalent1Id', 'NodeEffect1Id'},
        'WeaponModel': {'WeaponId', 'WeaponClass'}, 'ImplantModel': {'ImplantTypeId', 'ImplantSlot', 'ImplantEffectId'},
        'EffectModel': {'EffectId'}, 'TalentModel': {'TalentId', 'Weapon'},
        'MatrixEffectModel': {'MatrixEffectId'}, 'ItemModel': {'ItemTypeId', 'ItemClass', 'TalentId'},
    }
    for col in gear_classes.LEVERS:
        required['WeaponModel'].add(col)
    for mapping in (cyberweapons.LASER_MAP, cyberweapons.CLAW_MAP):
        for _sheet, (model, col) in mapping:
            required.setdefault(model, set()).add(col)
    for mapping in consumables.SHEET_COLUMNS.values():
        for _sheet, model, col in mapping:
            required.setdefault(model, set()).add(col)
    required['ImplantModel'].update(implants.IMPLANT_LEVERS)
    with StaticData(source) as data:
        if data.database:
            answer = data.connection.execute('PRAGMA quick_check').fetchall()
            if answer != [('ok',)]:
                raise DataError('SQLite quick_check failed: %s' % answer)
        for model, cols in required.items():
            _columns, rows = data.read(model, cols)
            if not rows:
                raise DataError("%s: required content table %s has no rows" % (data.path, model))
        total = 0
        for model in data.tables():
            cols, rows = data.read(model)
            total += len(rows)
            print('%s: %d rows, %d columns' % (model, len(rows), len(cols)))
        digest = hashlib.sha256(data.path.read_bytes()).hexdigest() if data.database else 'CSV capture'
        print('Static source: %s\nSHA256: %s\n%d tables, %d rows; %d consumer contracts checked.' %
              (data.path, digest, len(data.tables()), total, len(required)))
        print('Runtime information: NOT RUN here; use probe/campaign captures.')
        if data.database and not data.locale:
            print('Locale unavailable at %s; display labels use explicit locale keys.' % data.locale_path)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    add_argument(parser)
    parser.add_argument('--check', action='store_true', help='validate the database and consumer contracts')
    args = parser.parse_args()
    try:
        check(args.dump)
    except (DataError, OSError) as exc:
        parser.exit(2, 'REFUSED: %s\n' % exc)
