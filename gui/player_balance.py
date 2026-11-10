"""Workshop-owned player tuning and fresh official-data catalogs.

Only sparse adjustments live in config. Catalog rows, joins and numeric field
declarations are read from Official/data.db on every request. The explicitly
declared talent-icon field accepts literal keys. No save database is opened. SQL is emitted in the same order as the former implant rules:
individual adjustments first, then the global implant multipliers.
"""
import copy
import csv
import hashlib
import json
import math
from pathlib import Path
import re

import static_data
import gear_classes

FILE = 'ckf.player-balance.json'
TABLE_KEYS = {'Weapon': 'WeaponId', 'WeaponMod': 'WeaponModId', 'Armor': 'ArmorId', 'Implant': 'ImplantTypeId',
              'Talent': 'TalentId', 'Effect': 'EffectId', 'MatrixEffect': 'MatrixEffectId',
              'MissionAdvantage': 'AdvantageTypeId', 'Trait': 'TraitId', 'Rule': 'RuleId', 'Item': 'ItemTypeId'}
MOD_CATEGORIES = ('Weapon Mods', 'Crafted Intrinsic', 'Intrinsic')
MULTIPLIERS = {'Cost': 'Price', 'InstallTime': 'Installation time', 'ImplantStress': 'Implant stress'}
# The limit-break edits remain exclusively in Hard Mode.
HARDMODE_EFFECTS = {10505, 10507}
# Enemy Balance owns its spawn-level cap, including in Workshop exports.
ENEMY_RULES = {'82'}
STANDALONE_RULES = {'83': 'Party Size Mod', '84': 'Faster Contact Limit Breaks',
                    '85': 'Faster Contact Limit Breaks'}
METADATA = {'Locked', 'FactionId', 'ServiceOptionId', 'Asset3DTypeId', 'ModClassId', 'ModSlot',
            'ShotVFXCount', 'WeaponClass', 'ImplantClass', 'ImplantSlot',
            'ImplantLevel', 'ImplantConflictId', 'Deactivated', 'BackstoryGroup',
            'InstallJobId', 'EffectClassification', 'EffectClearType', 'EffectPurgeType',
            'EffectGroupId', 'EffectOwner', 'EffectHealType', 'TraitClass', 'TraitGroup',
            'AdvantageClass', 'ActionTypeId', 'ActionOptionId', 'ArmorClass',
            'TalentTypeId', 'TalentLevel', 'LevelCost', 'ActionId', 'PetProxy',
            'TalentIsCyber', 'TalentReqCyber', 'TalentIsFace', 'TalentIsMatrixOnly',
            'TalentIsActive', 'GameEventTrigger', 'Weapon', 'WeaponMode', 'PreReq',
            'ExtraAsset', 'FilterTypeId', 'AltRuleType', 'AnimationKey', 'KeepSelected',
            'AlternateAdjustment', 'AltOverride', 'AlternateCharge', 'Counter'}
METADATA.update({'EffectTypeId', 'MatrixEffectTypeId', 'ImplantEffectId', 'ImplantTraitGroup',
                 'MatrixEffectId', 'EffectTriggerType', 'TriggerEffectId', 'WoundTraitId',
                 'ImplantTalentId', 'ArmorEffectId', 'TargetEffect',
                 'SelfEffect', 'MatrixEffect', 'Token'})
METADATA.update({'ItemClass', 'LeverageClass', 'TalentId'})
ITEM_CLASSES = {1: 'Medical', 2: 'Grenades', 3: 'Devices', 4: 'Chems', 6: 'Sploitkits', 7: 'Matrix'}
ITEM_TAG_LOCALES = {1: 'Medical', 2: 'Demolition', 3: 'Tech', 4: 'Drugs', 6: 'Leverage', 7: 'HackingDrugs'}
# Explicit text-assignment declaration; other fields keep the numeric grammar.
TEXT_FIELDS = {'Talent': {'IconPng'}}
# ContactService.ServiceFlow scopes the option id: for example the official
# ContactService rows 1, 4 and 7 use option 1 for different catalogs.
SERVICE_FLOWS = {'Weapon': '1', 'WeaponMod': '3', 'Item': '7', 'Implant': '8'}
# Generic-pool classification policy. Named MissionLootGroupIds captured in
# _id_constants.csv: WeaponDeprecated, Weapon, WeaponMod, BlueprintWeapon,
# BlueprintWeaponMod and BlueprintWeaponModIntrinsic. Other explicit loot
# references alone do not establish a general loot route.
GENERIC_GEAR_LOOT_GROUPS = {'Weapon': {'7000', '100000'}, 'WeaponMod': {'8000'},
                            'Item': {'1000', '1001', '1002', '1003', '1009'}}
GENERIC_BLUEPRINT_LOOT_GROUPS = {'Weapon': {'50000'}, 'WeaponMod': {'60000', '60001'},
                                 'Item': {'2000', '2001', '2002', '2003'}}
BLUEPRINT_OUTPUT_TABLES = {'1': 'Weapon', '3': 'Item', '5': 'WeaponMod', '7': 'Weapon'}
LABELS = {'ApCost': 'AP cost', 'CritMultiBase': 'Crit damage', 'CritMultiStealth': 'Stealth crit damage',
          'ImplantStress': 'Stress', 'InstallTime': 'Install time', 'BaseCost': 'Price',
          'BallisticDamage1': 'Ballistic · 1', 'BallisticDamage2': 'Ballistic · 2',
          'PhysicalDamage1': 'Physical · 1', 'PhysicalDamage2': 'Physical · 2',
          'PureDamage1': 'Pure · 1', 'PureDamage2': 'Pure · 2',
          'ActionPoints1': 'AP · 1', 'ActionPoints2': 'AP · 2',
          'Accuracy1': 'Accuracy · 1', 'Accuracy2': 'Accuracy · 2',
          'TargetEffectDuration': 'Target duration', 'RechargeTurns': 'Recharge',
          'MaxCharges': 'Charges', 'EffectTypeId': 'Effect', 'MatrixEffectTypeId': 'Matrix effect'}
CLASS_NAMES = {1: 'Melee', 2: 'Pistol', 3: 'Assault Rifle', 4: 'Shotgun',
               5: 'E-Rifle', 6: 'Sniper Rifle', 7: 'Canine Attack Rig', 9: 'Drone assault rifles',
               10: 'SMG', 11: 'Revolver', 12: 'Urban Assault', 14: 'Railgun',
               16: 'Claws', 17: 'Eye Lasers', 18: 'Drone SMGs', 19: 'Drone energy rifles'}
WEAPON_ORDER = [1, 2, 11, 10, 4, 5, 12, 3, 6, 14, 16, 17]
DRONE_CLASSES = {7, 9, 18, 19}
SLOT_NAMES = {1: 'Skin', 2: 'Spinal', 3: 'Deep Brain', 4: 'Fast Brain', 5: 'Skeletal',
              6: 'Arms', 7: 'Legs', 8: 'Ocular', 9: 'Heart', 10: 'Lungs', 11: 'Quantum Rider'}
SLOT_ORDER = [8, 6, 1, 5, 3, 4, 2, 9, 10, 7]
# Explicit presentation order, independent of SQL's physical column order.
WEAPON_GROUPS = [
    ('Damage 1', ['PhysicalDamage1', 'BallisticDamage1', 'PureDamage1']),
    ('Damage 2', ['PhysicalDamage2', 'BallisticDamage2', 'PureDamage2']),
    ('Damage', ['PhysicalDamageMod', 'BallisticDamageMod', 'PureDamageMod']),
    ('Accuracy', ['Accuracy1', 'Accuracy2', 'AccuracyMod']),
    ('Armor crit', ['ArmorCritRate1', 'ArmorCritRate2', 'ArmorCritRateMod']),
    ('Crit damage', ['CritMultiStealth', 'CritMultiBase']),
    ('Range', ['OptimalRangeA1', 'OptimalRangeB1', 'OptimalRangeA2', 'OptimalRangeB2',
               'OptimalRangeAMod', 'OptimalRangeBMod', 'MaxRange', 'MaxRangeMod']),
    ('Recoil', ['RecoilRate1', 'RecoilRate2', 'RecoilRateMod']),
    ('', ['ShotVolume']), ('Arc', ['AngleFire1', 'AngleFire2', 'AngleFireMod']),
    ('', ['ReloadSize', 'WeaponEffect'])]
LEADING_COLUMNS = ['PowerLevel', 'Rarity', 'Cost']
GEAR_ORDER = LEADING_COLUMNS + [c for _, columns in WEAPON_GROUPS for c in columns]


def natural(value):
    return [int(x) if x.isdigit() else x.casefold() for x in re.split(r'(\d+)', value)]


def effective(doc, table, row, column):
    value = float(row.get(column, '0') or 0)
    parsed = adjustment(doc['tables'].get(table, {}).get(row[TABLE_KEYS[table]], {}).get(column, ''))
    if parsed is not None:
        op, n = parsed
        value = round(n if op == 'set' else value + n if op == 'add' else value * n)
    if table == 'Implant' and column in MULTIPLIERS:
        value = round(value * doc.get('implantMultipliers', {}).get(column, 1))
    return value


def column_presentation(table, column):
    if column == 'PowerLevel':
        return {'label': 'PL'}
    if table not in ('Weapon', 'WeaponMod'):
        return {}
    for group, columns in WEAPON_GROUPS:
        if column not in columns:
            continue
        short = {'CritMultiStealth': 'Stealth', 'CritMultiBase': 'Non-stealth',
                 'ShotVolume': 'Noise', 'ReloadSize': 'Reload size', 'WeaponEffect': 'Weapon effect',
                 'MaxRange': 'Max', 'MaxRangeMod': 'Max'}
        if column.startswith(('PhysicalDamage', 'BallisticDamage', 'PureDamage')):
            title = column.split('Damage')[0]
        elif column.startswith('OptimalRange'):
            title = ('Optimal min' if column[12] == 'A' else 'Optimal max')
            if column[-1:] in ('1', '2'):
                title += ' ' + column[-1]
        elif column[-1:] in ('1', '2'):
            title = column[-1]
        else:
            title = 'Modifier'
        return {'group': group, 'label': short.get(column, title)}
    return {}


def encode(value):
    return (json.dumps(value, indent=2, ensure_ascii=False) + '\n').encode('utf-8')


def empty():
    return {'format': 1, 'implantMultipliers': dict.fromkeys(MULTIPLIERS, 1), 'tables': {}}


def csv_rows(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def load(config_dir):
    path = Path(config_dir) / FILE
    if not path.exists():
        return empty()
    doc = json.loads(path.read_text(encoding='utf-8-sig'))
    if doc.get('format') != 1 or not isinstance(doc.get('tables'), dict):
        raise ValueError('%s: unsupported tuning format' % path)
    return doc


def adjustment(value):
    """Workshop numbers set, including negatives; +N adds and xN multiplies."""
    spec = str(value).strip()
    if spec.startswith('-'):
        spec = '=' + spec
    op, number, ok = gear_classes.parse_adjust(spec)
    if not ok:
        raise ValueError('Use a number, =N, +N, -N or xN: %s' % value)
    if op == gear_classes.NONE:
        return None
    if not math.isfinite(number):
        raise ValueError('Adjustment must be finite')
    return op, number


def normalize_adjustment(value):
    """Remove a redundant assignment marker without creating an add command."""
    spec = str(value).strip()
    adjustment(spec)
    if spec.startswith('='):
        spec = spec[1:].strip()
        if spec.startswith('+'):
            spec = spec[1:]
    return spec


def label(column):
    return LABELS.get(column, re.sub(r'(?<=[a-z0-9])(?=[A-Z])', ' ', column))


def identity(source):
    """Stat and hash within the transaction; no cached baseline can pass this."""
    source.assert_unchanged()
    result = {'path': str(source.path), 'sha256': hashlib.sha256(source.path.read_bytes()).hexdigest()}
    source.assert_unchanged()
    return result


def declarations(source, table):
    if table not in TABLE_KEYS or table not in source.schema:
        raise ValueError('Unsupported/missing content table: %s' % table)
    return {r[1]: r[2] for r in source.schema[table] if not r[5] and
            (any(t in r[2].upper() for t in ('INT', 'REAL', 'NUM', 'FLOAT', 'DOUBLE'))
             or r[1] in TEXT_FIELDS.get(table, set()))}


def protected_rows(config_dir, source):
    protected = {'Effect': set(map(str, HARDMODE_EFFECTS)), 'Trait': set()}
    if config_dir is None:
        return protected
    root = Path(config_dir) / 'ckf.hardmode.d'
    limits = root / 'EffectModel.limitbreak.csv'
    if limits.exists():
        protected['Effect'].update(row['EffectId'] for row in csv_rows(limits))
    fatigue = root / 'fatigue.json'
    if fatigue.exists():
        data = json.loads(fatigue.read_text(encoding='utf-8-sig'))
        protected['Trait'].update(str(data.get('tier%d' % n, {}).get('traitId', 0)) for n in (1, 2, 3))
        for row in source.read('TraitModel')[1]:
            if row['TraitId'] in protected['Trait']:
                protected['Effect'].add(row['EffectTypeId'])
    return protected


def validate(doc, source, config_dir=None):
    if doc.get('format') != 1 or set(doc) - {'format', 'implantMultipliers', 'tables'}:
        raise ValueError('Unsupported player tuning document')
    for col, value in doc.get('implantMultipliers', {}).items():
        if col not in MULTIPLIERS or isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not 0 <= value <= 10:
            raise ValueError('Invalid implant multiplier: %s' % col)
    protected = protected_rows(config_dir, source)
    weapon_assets = None
    known_icons = None
    item_classes = None
    for table, records in doc['tables'].items():
        columns = declarations(source, table)
        rows = {r[TABLE_KEYS[table]]: r for r in source.read(table + 'Model')[1]}
        if not isinstance(records, dict):
            raise ValueError('%s overrides must be keyed by id' % table)
        for rid, fields in records.items():
            if rid not in rows:
                raise ValueError('%s %s no longer exists in the official database; review its overrides' % (table, rid))
            if rid in protected.get(table, set()):
                raise ValueError('%s %s belongs to Hard Mode Fatigue/limit breaks' % (table, rid))
            if table == 'Rule' and rid in STANDALONE_RULES:
                raise ValueError('Rule %s belongs to %s; edit and export it in its own section.'
                                 % (rid, STANDALONE_RULES[rid]))
            if table == 'Rule' and rid in ENEMY_RULES:
                raise ValueError('Rule %s belongs to Enemy Balance; it cannot be saved or exported by Player Balance' % rid)
            if not isinstance(fields, dict):
                raise ValueError('Invalid fields for %s %s' % (table, rid))
            for col, value in fields.items():
                if col not in columns:
                    raise ValueError('%s.%s is not an editable content field' % (table, col))
                if col in TEXT_FIELDS.get(table, set()):
                    if known_icons is None:
                        known_icons = {r['IconPng'] for r in source.read('TalentModel', ('IconPng',))[1] if r['IconPng']}
                    if not isinstance(value, str) or (value and value not in known_icons):
                        raise ValueError('Talent %s: choose an existing talent icon' % rid)
                    continue
                parsed = adjustment(value)
                if table == 'Item' and col == 'ItemClass' and parsed is not None:
                    if item_classes is None:
                        item_classes = set(map(str, ITEM_CLASSES)) | {r['ItemClass'] for r in source.read('ItemModel')[1]}
                    if str(int(effective(doc, table, rows[rid], col))) not in item_classes:
                        raise ValueError('Item %s: choose an existing consumable tag' % rid)
                if table == 'Weapon' and col == 'Asset3DTypeId' and parsed is not None:
                    if weapon_assets is None:
                        weapon_assets = {r['WeaponModelId'] for r in source.read('Weapon3DAssetModel')[1]}
                    op, number = parsed
                    if op != 'set' or not number.is_integer() or str(int(number)) not in weapon_assets:
                        raise ValueError('Weapon %s: choose an existing icon / model assignment' % rid)


def _effective_enemy_ids(source, config_dir, column):
    key = 'MonsterTypeId'
    rows = {r[key]: r for r in source.read('MonsterTypeModel')[1]}
    overlay = Path(config_dir) / 'ckf.hardmode.d/MonsterTypeModel.csv'
    if overlay.is_file():
        for r in csv_rows(overlay):
            rows[r[key]] = {**rows.get(r.get('_clone') or r[key], {}),
                            **{k: v for k, v in r.items() if v and not k.startswith('_')}}
    return {r.get(column) for r in rows.values()}


def blueprint_drop_references(source, tables=('Weapon', 'WeaponMod')):
    """Positive blueprint-drop evidence, keyed by output table and id.

    Constants.BlueprintClass: Weapon=1, Item=3, WeaponMod=5, PetWeapon=7.
    LootTypes.Blueprint=1. Blueprint service assignments are not drop evidence.
    """
    refs = {table: {} for table in tables}
    loot = {}
    for row in source.read('MissionLootModel', ('MissionLootId', 'LootKey', 'LootTypeId'))[1]:
        if row['LootTypeId'] == '1':
            loot.setdefault(row['LootKey'], []).append(row['MissionLootId'])
    for row in source.read('BlueprintModel', ('BlueprintId', 'OutputId', 'BlueprintClassId', 'Lootable'))[1]:
        table = BLUEPRINT_OUTPUT_TABLES.get(row['BlueprintClassId'])
        if table not in refs:
            continue
        prefix = 'Blueprint ' + row['BlueprintId']
        evidence = ([prefix + ' (Lootable)'] if row['Lootable'] == '1' else [])
        evidence.extend(prefix + ' via MissionLoot ' + rid for rid in loot.get(row['BlueprintId'], []))
        if evidence:
            refs[table].setdefault(row['OutputId'], []).extend(evidence)
    return refs


def contact_services(source):
    """Apply the editor's cap policy within each (flow, group) service ladder.

    UpgradeReady=2 is terminal under the editor's acquisition policy. The first
    such ServiceLevel caps the ladder; DisplayLevel is only a presentation label.
    Ladders without a terminal marker retain their existing inclusive behavior.
    """
    rows = source.read('ContactServiceModel', ('ServiceTypeId', 'ServiceFlow', 'ServiceOptionId',
                      'ServiceGroupId', 'ServiceLevel', 'DisplayLevel', 'UpgradeReady'))[1]
    caps = {}
    for row in rows:
        if row['UpgradeReady'] == '2':
            key = row['ServiceFlow'], row['ServiceGroupId']
            level = int(row['ServiceLevel'])
            previous = caps.get(key)
            if previous is None or level < previous['level']:
                caps[key] = {'level': level, 'ids': [row['ServiceTypeId']]}
            elif level == previous['level']:
                previous['ids'].append(row['ServiceTypeId'])
    result = []
    for row in rows:
        cap = caps.get((row['ServiceFlow'], row['ServiceGroupId']))
        attainable = cap is None or int(row['ServiceLevel']) <= cap['level']
        reason = '' if attainable else (
            'Unattainable: ServiceLevel %s exceeds cap %s for ServiceFlow %s, ServiceGroupId %s; '
            'ContactService %s has UpgradeReady=2.' %
            (row['ServiceLevel'], cap['level'], row['ServiceFlow'], row['ServiceGroupId'], ', '.join(cap['ids'])))
        result.append(dict(row, attainable=attainable, cap=cap, unattainableReason=reason))
    return result


def player_gear_references(source, doc=None, blueprint_refs=None, source_kinds=None):
    """Inclusive positive acquisition references, keyed by table and content id.

    BlueprintClass Weapon=1 / WeaponMod=5: CoreRPG_v1.dll, Constants.BlueprintClass.
    LootTypes Blueprint=1 / Weapon=8 / WeaponMod=10: _id_constants.csv.
    Blueprint ServiceOptionId does not establish acquisition. ContactService
    12010 carries Srv_BuyBlueprint_Weapons_PL1; Official/en-US.json,
    BlockDesc.91079_Male, explicitly describes selling weapon blueprints.
    Story equipment: official BlockCondition 2526, Equip for
    PCP_RetireSleep_Soldier, names Weapon 1028 and 4025 in the first two values.
    Do not require Lootable on a blueprint explicitly present in mission loot.
    This is a catalog policy, not a campaign reachability or probability test.
    """
    doc = doc or empty()
    rows = {table: source.read(table + 'Model')[1] for table in ('Weapon', 'WeaponMod')}
    known = {table: {r[TABLE_KEYS[table]] for r in records} for table, records in rows.items()}
    refs = {table: {} for table in rows}

    def add(table, rid, evidence, kind):
        if rid in known[table]:
            entries = refs[table].setdefault(rid, [])
            if evidence not in entries:
                entries.append(evidence)
            if source_kinds is not None:
                source_kinds.setdefault(table, {}).setdefault(rid, set()).add(kind)

    services = contact_services(source)
    for table, records in rows.items():
        for row in records:
            options = {row['ServiceOptionId'], str(int(effective(doc, table, row, 'ServiceOptionId')))}
            for service in services:
                if (service['attainable'] and service['ServiceFlow'] == SERVICE_FLOWS[table] and
                        int(service['ServiceOptionId']) > 0 and service['ServiceOptionId'] in options):
                    add(table, row[TABLE_KEYS[table]], 'ContactService ' + service['ServiceTypeId'], 'service')

    loot = source.read('MissionLootModel', ('MissionLootId', 'LootKey', 'LootTypeId'))[1]
    for row in loot:
        for table, kind in (('Weapon', '8'), ('WeaponMod', '10')):
            if row['LootTypeId'] == kind:
                add(table, row['LootKey'], 'MissionLoot ' + row['MissionLootId'], 'loot')
    if blueprint_refs is None:
        blueprint_refs = blueprint_drop_references(source)
    for table in rows:
        for rid, evidence in blueprint_refs[table].items():
            for reference in evidence:
                add(table, rid, reference, 'blueprint')

    # Crafted Intrinsic is an explicit player-crafting catalog inclusion,
    # independent of a detachable-item drop or blueprint resale assignment.
    class_mods = source.read('WeaponClassModModel')[1]
    for row in rows['WeaponMod']:
        if mod_fitment(source, row, class_mods)['category'] == 'Crafted Intrinsic':
            add('WeaponMod', row['WeaponModId'], 'Player crafting option (Crafted Intrinsic)', 'crafting')

    for row in source.read('TalentModel')[1]:
        if row['TalentIsCyber'] == '1':
            for wid in {row['Weapon'], str(int(effective(doc, 'Talent', row, 'Weapon')))}:
                add('Weapon', wid, 'Cyber talent ' + row['TalentId'], 'cyberware')
    # Explicit player-pet catalog policy. Constants.WeaponClass declares
    # DogWeapon=7 and CatWeapon=8; official Job 9 owns pet type 4 (Hunder),
    # and Job 4 owns type 5 (Assassin, with Lynx/Snow Leopard jobs 30/31).
    pet_weapon_classes = {'4': '7', '5': '8'}
    for job in source.read('JobModel', ('JobId', 'JobType', 'PetOwnerTypeId'))[1]:
        weapon_class = pet_weapon_classes.get(job['PetOwnerTypeId'])
        if job['JobType'] == '1' and weapon_class:
            for weapon in rows['Weapon']:
                if weapon['WeaponClass'] == weapon_class:
                    add('Weapon', weapon['WeaponId'], 'Job ' + job['JobId'] +
                        ' player pet (weapon class ' + weapon_class + ')', 'pet')
    for row in source.read('DroneChassisModel')[1]:
        for field in ('WeaponType1', 'WeaponType2'):
            # Chassis slots declare weapon classes (e.g. row 1 names class 18),
            # not Weapon ids. Keep every tier of a referenced class.
            for weapon in rows['Weapon']:
                if row[field] not in ('', '0', '-1') and weapon['WeaponClass'] == row[field]:
                    add('Weapon', weapon['WeaponId'], 'PetChassis ' + row['DroneChassisType'] +
                        '.' + field + ' (weapon class ' + row[field] + ')', 'pet')
    for row in source.read('DronePrebuiltModel')[1]:
        add('Weapon', row['Weapon'], 'PetPrebuilt ' + row['DroneType'], 'pet')
    for row in source.read('BlockConditionModel', ('BlockConditionId', 'ConditionType', 'ActorId',
                                                  'ConditionValue', 'ConditionValue2'))[1]:
        if row['ConditionType'] == 'Equip':
            for field in ('ConditionValue', 'ConditionValue2'):
                add('Weapon', row[field], 'BlockCondition ' + row['BlockConditionId'] +
                    ' Equip (' + row['ActorId'] + ')', 'mission')
    return refs


def player_implant_references(source, doc=None, source_kinds=None):
    """Inclusive cyberware policy: services, starting equipment, story candidates.

    Player-job requirements retain every matching implant class, including jobs
    not enabled in character selection. Nonzero Deactivated entries and their
    linked variants are retained by explicit maintainer policy; this does not
    assert an exact campaign-to-implant activation mapping.
    """
    doc = doc or empty()
    rows = source.read('ImplantModel', ('ImplantTypeId', 'ServiceOptionId', 'ImplantClass',
                                      'BackstoryGroup', 'Deactivated'))[1]
    known = {r['ImplantTypeId'] for r in rows}
    refs = {'Implant': {}}

    def add(rid, evidence, kind):
        if rid in known:
            entries = refs['Implant'].setdefault(rid, [])
            if evidence not in entries:
                entries.append(evidence)
            if source_kinds is not None:
                source_kinds.setdefault('Implant', {}).setdefault(rid, set()).add(kind)

    services = [r for r in contact_services(source) if r['ServiceFlow'] == SERVICE_FLOWS['Implant']
                and r['attainable'] and int(r['ServiceOptionId']) > 0]
    for row in rows:
        options = {row['ServiceOptionId'], str(int(effective(doc, 'Implant', row, 'ServiceOptionId')))}
        for service in services:
            if service['ServiceOptionId'] in options:
                add(row['ImplantTypeId'], 'ContactService ' + service['ServiceTypeId'], 'service')
    backstories = source.read('BackstoryModel', ('BackstoryId', 'BackstoryGroup', 'Implant',
                                                'Implant1', 'Implant2', 'Implant3'))[1]
    groups = {r['BackstoryGroup'] for r in backstories} - {'', '0', '-1'}
    for row in backstories:
        for field in ('Implant', 'Implant1', 'Implant2', 'Implant3'):
            add(row[field], 'Backstory %s.%s' % (row['BackstoryId'], field), 'starting')
    for row in rows:
        if row['BackstoryGroup'] in groups:
            add(row['ImplantTypeId'], 'Implant %s.BackstoryGroup %s' %
                (row['ImplantTypeId'], row['BackstoryGroup']), 'starting')
    for job in source.read('JobModel', ('JobId', 'JobType', 'ReqCyberClass1Id'))[1]:
        if job['JobType'] == '1' and job['ReqCyberClass1Id'] not in ('', '0', '-1'):
            for row in rows:
                if row['ImplantClass'] == job['ReqCyberClass1Id']:
                    add(row['ImplantTypeId'], 'Job %s.ReqCyberClass1Id %s (inclusive class policy)' %
                        (job['JobId'], job['ReqCyberClass1Id']), 'starting')
    for row in source.read('DronePrebuiltModel', ('DroneType', 'CyberSlot1', 'CyberSlot2',
                                                'CyberSlot3', 'CyberSlot4', 'CyberSlot5'))[1]:
        for field in ('CyberSlot1', 'CyberSlot2', 'CyberSlot3', 'CyberSlot4', 'CyberSlot5'):
            add(row[field], 'PetPrebuilt %s.%s' % (row['DroneType'], field), 'starting')
    activations = [r['BlockConditionId'] for r in source.read('BlockConditionModel',
                   ('BlockConditionId', 'ConditionType'))[1] if r['ConditionType'] == 'ActivateCyber']
    story = '; ActivateCyber BlockCondition ' + ', '.join(activations) if activations else ''
    for row in rows:
        flag = int(row['Deactivated'] or 0)
        if flag:
            evidence = 'Implant %s.Deactivated %s (potential story cyberware%s)' % (row['ImplantTypeId'], flag, story)
            add(row['ImplantTypeId'], evidence, 'story')
            if flag > 0 and str(flag) != row['ImplantTypeId']:
                add(str(flag), evidence + ' linked variant', 'story')
    return refs


def implant_service_fallbacks(acquisition, source_kinds):
    """Name the non-service sources admitted by the inclusive implant policy."""
    return {rid: {'label': ' / '.join(label for kind, label in
                    (('starting', 'Starting Gear'), ('story', 'Mission'))
                    if kind in source_kinds.get('Implant', {}).get(rid, set())),
                  'detail': 'Availability references:\n' + '\n'.join(evidence)}
            for rid, evidence in acquisition.get('Implant', {}).items()}


def gear_service_fallbacks(source, acquisition, source_kinds):
    """Describe non-service availability; the renderer still resolves services first."""
    routes = {table: {} for table in acquisition}

    def route(table, rid):
        return routes[table].setdefault(rid, {'loot': False, 'blueprint': False, 'generic': False})

    blueprint_outputs = {}
    for row in source.read('BlueprintModel', ('BlueprintId', 'OutputId', 'BlueprintClassId', 'Lootable'))[1]:
        table = BLUEPRINT_OUTPUT_TABLES.get(row['BlueprintClassId'])
        if table not in routes:
            continue
        blueprint_outputs[row['BlueprintId']] = table, row['OutputId']
        if row['Lootable'] == '1':
            entry = route(table, row['OutputId'])
            entry.update(blueprint=True, generic=True)
    for row in source.read('MissionLootModel', ('LootTypeId', 'LootKey', 'LootGroupId'))[1]:
        table = {'8': 'Weapon', '10': 'WeaponMod', '2': 'Item'}.get(row['LootTypeId'])
        if table in routes:
            entry = route(table, row['LootKey'])
            entry['loot'] = True
            entry['generic'] |= row['LootGroupId'] in GENERIC_GEAR_LOOT_GROUPS[table]
        elif row['LootTypeId'] == '1' and row['LootKey'] in blueprint_outputs:
            table, rid = blueprint_outputs[row['LootKey']]
            entry = route(table, rid)
            entry['blueprint'] = True
            entry['generic'] |= row['LootGroupId'] in GENERIC_BLUEPRINT_LOOT_GROUPS[table]

    result = {table: {} for table in acquisition}
    other_labels = (('crafting', 'Crafting'), ('cyberware', 'Cyberware'), ('pet', 'Pet'))
    for table, records in acquisition.items():
        for rid, evidence in records.items():
            entry = routes[table].get(rid, {})
            kinds = source_kinds.get(table, {}).get(rid, set())
            other = [label for kind, label in other_labels if kind in kinds]
            drops = [label for key, label in (('loot', 'Loot'), ('blueprint', 'Blueprint')) if entry.get(key)]
            if (drops or 'mission' in kinds) and not entry.get('generic') and not other:
                labels = ['Mission']
            else:
                labels = drops or other or (['Mission'] if 'mission' in kinds else [])
            result[table][rid] = {'label': ' / '.join(labels),
                                  'detail': 'Availability references:\n' + '\n'.join(evidence)}
    return result


def item_service_fallbacks(source, blueprint_refs=None):
    """Use the weapon source policy for typed item drops and blueprints.

    LootTypes.Item=2 and the generic Item/BlueprintItem groups are captured in
    sheets/raw/_id_constants.csv. BlueprintClass.Item=3 is declared in
    CoreRPG_v1.dll metadata. Output ids remain scoped to the Item table.
    """
    if blueprint_refs is None:
        blueprint_refs = blueprint_drop_references(source, ('Item',))['Item']
    refs = copy.deepcopy(blueprint_refs)
    for row in source.read('MissionLootModel', ('MissionLootId', 'LootTypeId', 'LootKey'))[1]:
        if row['LootTypeId'] == '2':
            refs.setdefault(row['LootKey'], []).append('MissionLoot ' + row['MissionLootId'])
    kinds = {}
    # Explicit story grant: official BlockCondition 875 names Item 1100;
    # Dialog.D_PGen_Amnesia_M1_Intro.10 describes the carried EPI-X injectors.
    for row in source.read('BlockConditionModel', ('BlockConditionId', 'ConditionType', 'ConditionValue'))[1]:
        if row['ConditionType'] == 'AddItem':
            rid = row['ConditionValue']
            refs.setdefault(rid, []).append('BlockCondition ' + row['BlockConditionId'] + ' AddItem')
            kinds.setdefault(rid, set()).add('mission')
    return gear_service_fallbacks(source, {'Item': refs}, {'Item': kinds})['Item']


def special_rules(source):
    """Pass game localization through, including unresolved format arguments."""
    result = {}
    for key, title in source.locale.items():
        match = re.fullmatch(r'Gear\.Weapon\.SpecialRule\.(\d+)', key)
        if not match or not isinstance(title, str):
            continue
        description = source.locale.get(key + '.Rule', '')
        result[match[1]] = {'title': title, 'description': description
                            if isinstance(description, str) else '', 'key': key}
    return result


def mod_fitment(source, row, class_mods):
    """Use declared mod classes, slot labels and per-mod exclusions.

    Crafting integrations (200+) have their own locale declarations; do not
    invent a class mapping by subtracting 200. Unknown classes stay explicit.
    """
    modclass, slot = row['ModClassId'], row['ModSlot']
    key = 'Table.Column.ModType.' + modclass
    declared = source.locale.get(key)
    declared = declared if isinstance(declared, str) and declared else None
    classes = [int(c['WeaponClassId']) for c in class_mods
               if any(c['Slot%dModClassId' % n] == modclass for n in range(1, 7))]
    excluded = {int(v) for v in re.findall(r'\d+', row['Exclusions'])} - {0}
    classes = [c for c in classes if c not in excluded]
    order = [1, 2, 11, 10, 3, 12, 4, 5, 6, 14]
    classes.sort(key=lambda c: (order.index(c) if c in order else len(order), c))
    weapons = '+'.join(CLASS_NAMES.get(c, 'Weapon class %s' % c) for c in classes)
    slot_match = re.search(r'(Barrel|Body Mod|Optic|Scope|Ion Batt|Grip)$', declared or '')
    if weapons:
        category = (slot_match[1] if slot_match else declared) or ('Slot ' + slot)
        title = weapons + ' · ' + category
    else:
        title = declared or ('Unresolved mod class ' + modclass)
        if excluded:
            title += ' · excludes ' + '+'.join(CLASS_NAMES.get(c, str(c)) for c in sorted(excluded))
    # Intrinsic and integration slot ids remain visible even where the locale
    # uses the same label as a detachable mod.
    numbered_slot = not slot_match or int(modclass) >= 100
    if numbered_slot:
        title += ' · slot ' + slot
    category = ('Intrinsic' if re.search(r'\bintrinsic\b', declared or '', re.IGNORECASE) else
                'Crafted Intrinsic' if numbered_slot else 'Weapon Mods')
    return {'title': title, 'category': category, 'key': key, 'declared': declared,
            'slot': slot, 'modClass': modclass, 'excluded': sorted(excluded),
            'mapped': bool(classes)}


def asset_picker(table, rows, pool, assets, doc, swap_scope=False, multiple_only=True):
    """Offer graphics already assigned within this weapon class or mod fitment."""
    ids = {r['Asset3DTypeId'] for r in pool}
    ids.update(str(int(effective(doc, table, r, 'Asset3DTypeId'))) for r in rows)
    ids = {rid for rid in ids if assets.get(rid, {}).get('Thumbnail')
           and (table == 'WeaponMod' or assets[rid].get('Resource'))}

    def display_name(path):
        token = path.rsplit('/', 1)[-1]
        prefix = r'^(WeaponMod_|weapon_mod_)' if table == 'WeaponMod' else r'^W_(AR|ARB|Shotgun|Melee|Pistol)_'
        return label(re.sub(prefix, '', token).replace('_', ' ')) or 'No icon'

    paths = sorted({assets[rid]['Thumbnail'] for rid in ids}, key=lambda path: (natural(display_name(path)), path))
    if swap_scope:
        rifle, sowo = 'CosmeticIcon/WeaponMod_Scope Rifle', 'CosmeticIcon/WeaponMod_Scope_Sowo'
        if rifle in paths and sowo in paths:
            a, b = paths.index(rifle), paths.index(sowo)
            paths[a], paths[b] = paths[b], paths[a]
    if table == 'WeaponMod' and multiple_only and len(paths) < 2:
        return None
    ranks = {path: i for i, path in enumerate(paths)}
    choices = []
    for rid in sorted(ids, key=lambda rid: (ranks[assets[rid]['Thumbnail']], int(rid))):
        a = assets[rid]
        owners = [r for r in pool if r['Asset3DTypeId'] == rid]
        examples = [r for r in rows if r['Asset3DTypeId'] == rid] or owners or rows
        namekey = 'WeaponName' if table == 'Weapon' else 'ModName'
        choices.append({'id': rid, 'name': display_name(a['Thumbnail']),
                        'token': a['Thumbnail'].rsplit('/', 1)[-1], 'thumbnail': a['Thumbnail'],
                        'resource': a['Resource'], 'examples': [r[namekey] for r in examples[:3]]})
    return {'column': 'Asset3DTypeId', 'choices': choices,
            'label': 'Visual' if table == 'WeaponMod' else 'Icon / model',
            'controlLabel': 'visual' if table == 'WeaponMod' else 'icon / model',
            'showExamples': False, 'regroup': table == 'WeaponMod',
            'assets': {rid: {'token': a['Thumbnail'].rsplit('/', 1)[-1], 'thumbnail': a['Thumbnail'],
                             'resource': a['Resource'], 'label': display_name(a['Thumbnail']),
                             'order': ranks.get(a['Thumbnail'], len(ranks))}
                       for rid, a in assets.items()}}


def consumable_editors(source, allrows, assets, doc, owners):
    """Themed item models, linked talent icons/assets, and gameplay category tags."""
    items, talents = allrows['Item'], allrows['Talent']
    tags = {str(c): source.locale.get('Gear.Item.Class.' + ITEM_TAG_LOCALES[c], ITEM_CLASSES[c]) for c in ITEM_CLASSES}
    for item in items.values():
        tags.setdefault(item['ItemClass'], 'Item class ' + item['ItemClass'])
    grenade_assets = {r['Asset3DTypeId'] for r in items.values() if r['ItemClass'] == '2'}
    grenade_assets.update(talents.get(r['TalentId'], {}).get('ExtraAsset', '0')
                         for r in items.values() if r['ItemClass'] == '2')
    grenade_assets.discard('0')

    def family(cls):
        return 'medical-drugs' if cls in ('1', '4', '7') else 'grenades' if cls == '2' else 'class-' + cls

    def official_family(item):
        talent = talents.get(item['TalentId'], {})
        return 'grenades' if (item['Asset3DTypeId'] in grenade_assets or talent.get('ExtraAsset') in grenade_assets) else family(item['ItemClass'])

    def icon_name(value):
        token = re.sub(r'^talent_item_', '', value).replace('_', ' ')
        token = re.sub(r'^combatdrug', 'Combat Drug ', token, flags=re.I)
        return label(token).strip().title()

    def model_choice(aid):
        asset = assets.get(aid, {})
        path = asset.get('Resource', '')
        return {'id': aid, 'name': label(path.rsplit('/', 1)[-1].replace('_', ' ')) if path else ('None' if aid == '0' else 'Asset ' + aid),
                'detail': 'Asset %s\nModel: %s\nIcon: %s' % (aid, path or '(none)', asset.get('Thumbnail', '') or '(none)')}

    pools = {}
    for item in items.values():
        pool = pools.setdefault(official_family(item), {'icons': set(), 'models': set(), 'extras': {'0'}})
        if assets.get(item['Asset3DTypeId'], {}).get('Resource'):
            pool['models'].add(item['Asset3DTypeId'])
        talent = talents.get(item['TalentId'])
        if talent:
            if talent['IconPng']:
                pool['icons'].add(talent['IconPng'])
            extra = talent['ExtraAsset']
            if extra == '0' or assets.get(extra, {}).get('Resource'):
                pool['extras'].add(extra)
    families = {name: {'icons': [{'id': value, 'name': icon_name(value), 'detail': value} for value in sorted(pool['icons'], key=natural)],
                       'models': [model_choice(aid) for aid in sorted(pool['models'], key=int)],
                       'extras': [model_choice(aid) for aid in sorted(pool['extras'], key=int)]}
                for name, pool in pools.items()}
    records = {}
    for item in items.values():
        rid = item['ItemTypeId']
        cls = str(int(effective(doc, 'Item', item, 'ItemClass')))
        theme = official_family(item) if cls == item['ItemClass'] else family(cls)
        tid = str(int(effective(doc, 'Item', item, 'TalentId')))
        talent = talents.get(tid)
        record = {'classBase': item['ItemClass'], 'classCurrent': cls, 'family': theme,
                  'modelBase': item['Asset3DTypeId'], 'modelCurrent': str(int(effective(doc, 'Item', item, 'Asset3DTypeId'))),
                  'talent': None}
        if talent:
            record['talent'] = {'id': tid, 'iconBase': talent['IconPng'],
                'iconCurrent': doc['tables'].get('Talent', {}).get(tid, {}).get('IconPng', talent['IconPng']),
                'assetBase': talent['ExtraAsset'], 'assetCurrent': str(int(effective(doc, 'Talent', talent, 'ExtraAsset'))),
                'sharedWith': [name for oid, name in owners.get(('Talent', tid), {}).items() if oid != rid]}
        records[rid] = record
    return {'controls': {'tagColumn': 'ItemClass', 'modelColumn': 'Asset3DTypeId', 'iconColumn': 'IconPng',
                'talentAssetColumn': 'ExtraAsset', 'talentTable': 'Talent',
                'tags': [{'id': key, 'name': value.split(' (', 1)[0], 'detail': value} for key, value in sorted(tags.items(), key=lambda p: int(p[0]))],
                'families': families, 'modelAssets': {aid: model_choice(aid) for aid in assets}}, 'rows': records}


def knight_trait_groups(source):
    """Join creation backstory tags to Trait.TagMatch, then TraitGroup levels.

    Job 1 is Cyber Knight in JobModel. Exclude tags referenced by another
    job's backstory; a shared generic trait is not Knight-specific. Return
    the backstory/tag evidence instead of identifying traits by their names.
    """
    fields = ['BackstoryTrait'] + [r[1] for r in source.schema['Backstory']
                                  if r[1].startswith(('Trait1', 'Trait2'))]
    stories = source.read('BackstoryModel')[1]
    other = {r[c] for r in stories if r['JobTypeId'] != '1' for c in fields if r[c]}
    evidence = {}
    for row in stories:
        if row['JobTypeId'] != '1' or row['NewGame'] == '0':
            continue
        for field in fields:
            tag = row[field]
            if tag and tag not in other:
                evidence.setdefault(tag, []).append({'backstory': row['BackstoryId'], 'field': field})
    return {row['TraitGroup']: {'tag': row['TagMatch'], 'references': evidence[row['TagMatch']]}
            for row in source.read('TraitModel')[1] if row['TagMatch'] in evidence}


def service_catalog(source):
    """Localized assignments keyed by (flow, option), never option alone."""
    grouped = {table: {} for table in SERVICE_FLOWS}
    for row in contact_services(source):
        for table, flow in SERVICE_FLOWS.items():
            if row['ServiceFlow'] != flow:
                continue
            key = 'ContactService.Name.' + row['ServiceTypeId']
            name = source.locale.get(key, key)
            text = name + (' · L' + row['DisplayLevel'] if int(row['DisplayLevel']) > 0 else '')
            entry = grouped[table].setdefault(row['ServiceOptionId'], {'labels': [], 'references': []})
            if row['attainable'] and text not in entry['labels']:
                entry['labels'].append(text)
            entry['references'].append({'id': row['ServiceTypeId'], 'flow': flow,
                'level': row['ServiceLevel'], 'displayLevel': row['DisplayLevel'], 'locale': key,
                'attainable': row['attainable'], 'cap': row['cap'], 'unattainableReason': row['unattainableReason']})
    return {table: {option: {'label': ', '.join(entry['labels']), 'references': entry['references'],
                            'attainable': any(r['attainable'] for r in entry['references']),
                            'detail': 'ServiceOptionId %s; ServiceFlow %s; ContactService %s' %
                                      (option, SERVICE_FLOWS[table], ', '.join(r['id'] for r in entry['references']))
                                      + ''.join('\n' + r['unattainableReason'] for r in entry['references']
                                                if not r['attainable'])}
                    for option, entry in options.items()} for table, options in grouped.items()}


def consumable_links(allrows, doc):
    """Resolve saved pointers once, retaining missing-target observations."""
    links, owners = {}, {}
    for item in allrows['Item'].values():
        rid = item['ItemTypeId']
        linked = {'Item': item, 'ids': {}, 'warnings': []}

        def follow(table, pointer, name):
            linked['ids'][name] = pointer
            target = None if pointer in ('0', '-1', '') else allrows[table].get(pointer)
            if pointer not in ('0', '-1', '') and target is None:
                linked['warnings'].append('%s %s: %s %s was not found' % ('Item', rid, table, pointer))
            if target:
                owners.setdefault((table, pointer), {})[rid] = item['ItemName']
            return target

        action_id = str(int(effective(doc, 'Item', item, 'TalentId')))
        action = linked['Action'] = follow('Talent', action_id, 'Action')
        for name, table, field in [('Self effect', 'Effect', 'SelfEffect'), ('Target effect', 'Effect', 'TargetEffect'),
                                   ('Matrix effects', 'MatrixEffect', 'MatrixEffect')]:
            pointer = str(int(effective(doc, 'Talent', action, field))) if action else '0'
            linked[name] = follow(table, pointer, name)
        linked['Effects'] = linked['Self effect'] or linked['Target effect']
        links[rid] = linked
    return links, owners


def implant_links(allrows, doc):
    """Resolve implant effect assignments, retaining unresolved pointers."""
    links, owners = {}, {}
    for implant in allrows['Implant'].values():
        rid = implant['ImplantTypeId']
        linked = {'ids': {}, 'warnings': []}
        for heading, table, field in [('Effects', 'Effect', 'ImplantEffectId'),
                                      ('Matrix effects', 'MatrixEffect', 'MatrixEffectId')]:
            pointer = str(int(effective(doc, 'Implant', implant, field)))
            linked['ids'][heading] = pointer
            target = None if pointer in ('0', '-1', '') else allrows[table].get(pointer)
            linked[heading] = target
            if pointer not in ('0', '-1', '') and target is None:
                linked['warnings'].append('Implant %s: %s %s was not found' % (rid, table, pointer))
            if target:
                owners.setdefault((table, pointer), {})[rid] = implant['ImplantName']
        links[rid] = linked
    return links, owners


def cyberweapon_links(allrows, doc, weapons):
    """Join effective attack/effect pointers and retain all owning implants."""
    attacks = {w['WeaponId']: [] for w in weapons}
    for talent in allrows['Talent'].values():
        wid = str(int(effective(doc, 'Talent', talent, 'Weapon')))
        if wid in attacks:
            attacks[wid].append(talent)
    count = max((len(a) for a in attacks.values()), default=0)
    links, owners, blocks = {}, {}, []
    for index in range(count):
        prefix = 'Attack' if count == 1 else 'Attack %s' % (index + 1)
        blocks += [(prefix, 'Talent'), (prefix + ' self effect', 'Effect'),
                   (prefix + ' target effect', 'Effect'), (prefix + ' matrix effects', 'MatrixEffect')]
    implants = {}
    for implant in allrows['Implant'].values():
        for field in ('ImplantTalentId', 'ImplantTalentId2'):
            tid = str(int(effective(doc, 'Implant', implant, field)))
            implants.setdefault(tid, {})[implant['ImplantTypeId']] = implant
    for weapon in weapons:
        wid = weapon['WeaponId']
        actions = sorted(attacks[wid], key=lambda a: int(a['TalentId']))
        linked = {'ids': {}, 'warnings': [], 'implants': {}}
        if not actions:
            linked['warnings'].append('Weapon %s: no attack talent references this weapon' % wid)
        for index in range(count):
            prefix = 'Attack' if count == 1 else 'Attack %s' % (index + 1)
            action = actions[index] if index < len(actions) else None
            tid = action['TalentId'] if action else '0'
            linked[prefix] = action
            linked['ids'][prefix] = tid
            if action:
                owners.setdefault(('Talent', tid), {})[wid] = weapon['WeaponName']
                linked['implants'].update(implants.get(tid, {}))
            for suffix, table, field in [(' self effect', 'Effect', 'SelfEffect'),
                                         (' target effect', 'Effect', 'TargetEffect'),
                                         (' matrix effects', 'MatrixEffect', 'MatrixEffect')]:
                heading = prefix + suffix
                pointer = str(int(effective(doc, 'Talent', action, field))) if action else '0'
                target = None if pointer in ('0', '-1', '') else allrows[table].get(pointer)
                linked[heading] = target
                linked['ids'][heading] = pointer
                if pointer not in ('0', '-1', '') and target is None:
                    linked['warnings'].append('Weapon %s: %s %s was not found' % (wid, table, pointer))
                if target:
                    owners.setdefault((table, pointer), {})[wid] = weapon['WeaponName']
        links[wid] = linked
    return links, owners, blocks


def catalog(config_dir, database, document=None):
    """Build rows and visible columns from a fresh, complete official read."""
    try:
        doc = load(config_dir) if document is None else copy.deepcopy(document)
    except (ValueError, OSError) as exc:
        return {'document': empty(), 'file': FILE, 'pages': [], 'error': str(exc), 'database': None}
    result = {'document': doc, 'file': FILE, 'pages': [], 'error': None, 'database': None}
    if database is False:
        result['error'] = 'No official database selected.'
        return result
    try:
        with static_data.StaticData(database) as source:
            result['database'] = identity(source)
            validate(doc, source, config_dir)
            protected = protected_rows(config_dir, source)
            allrows = {t: {r[TABLE_KEYS[t]]: r for r in source.read(t + 'Model')[1]}
                       for t in TABLE_KEYS}
            assets = {r['WeaponModelId']: r for r in source.read('Weapon3DAssetModel')[1]}
            services = service_catalog(source)
            blueprint_refs = blueprint_drop_references(source, ('Weapon', 'WeaponMod', 'Item'))
            source_kinds = {}
            acquisition = player_gear_references(source, doc, blueprint_refs, source_kinds)
            service_fallbacks = gear_service_fallbacks(source, acquisition, source_kinds)
            acquisition.update(player_implant_references(source, doc, source_kinds))
            service_fallbacks['Implant'] = implant_service_fallbacks(acquisition, source_kinds)
            service_fallbacks['Item'] = item_service_fallbacks(source, blueprint_refs['Item'])
            item_links, item_owners = consumable_links(allrows, doc)
            cyberware_links, implant_owners = implant_links(allrows, doc)
            for trait in allrows['Trait'].values():
                if trait['TraitName'].startswith('Trait.Name.'):
                    trait['TraitName'] = source.locale.get('Trait.Name.' + trait['TraitGroup'] + '_Male', trait['TraitName'])

            def grid(table, rows, title, policy='varying'):
                cols = declarations(source, table)
                overrides = doc['tables'].get(table, {})
                visible, advanced = [], []
                for col in cols:
                    if col in TEXT_FIELDS.get(table, set()):
                        continue
                    values = {r.get(col, '') for r in rows}
                    has_override = any(overrides.get(r[TABLE_KEYS[table]], {}).get(col, '') != '' for r in rows)
                    interesting = policy == 'all' or (len(values) > 1 if policy == 'varying'
                                   else any(v not in ('', '0', '0.0') for v in values))
                    target = visible if has_override or (interesting and col not in METADATA) else advanced
                    target.append({'name': col, 'label': label(col), 'visibilityPolicy': policy,
                                   'metadata': col in METADATA, 'integer': 'INT' in cols[col].upper(),
                                   **column_presentation(table, col)})
                order = GEAR_ORDER if table in ('Weapon', 'WeaponMod') else LEADING_COLUMNS
                for columns in (visible, advanced):
                    for column in columns:
                        column['order'] = (order.index(column['name']) if column['name'] in order
                                           else len(order) + list(cols).index(column['name']))
                        column['leading'] = column['name'] in LEADING_COLUMNS
                    columns.sort(key=lambda c: c['order'])
                namekey = {'Weapon': 'WeaponName', 'Armor': 'ArmorName', 'Implant': 'ImplantName',
                           'WeaponMod': 'ModName',
                           'Trait': 'TraitName', 'Effect': 'EffectName', 'MatrixEffect': 'EffectName',
                           'Talent': 'TalentName', 'Item': 'ItemName'}.get(table)
                records = []
                for r in rows:
                    rid = r[TABLE_KEYS[table]]
                    name = r.get(namekey) if namekey else None
                    if table == 'MissionAdvantage':
                        name = source.locale.get('Advantage.Name.' + rid, 'Leverage ' + rid)
                    if table == 'Rule':
                        name = r['ConfigName']
                    records.append({'id': rid, 'name': name or title + ' ' + rid,
                                    'description': r.get('ConfigDesc', r.get('ItemDesc', '')),
                                    'baseline': {c: r[c] for c in cols},
                                    'readOnly': rid in protected.get(table, set()) or (table == 'Rule' and rid in ENEMY_RULES),
                                    'readOnlyReason': 'Managed by Enemy Balance' if table == 'Rule' and rid in ENEMY_RULES
                                                      else 'Managed by Hard Mode Fatigue / limit-break traits'})
                    if table in ('Weapon', 'WeaponMod'):
                        records[-1]['acquisition'] = acquisition[table].get(rid, [])
                        records[-1]['blueprintDrops'] = blueprint_refs[table].get(rid, [])
                        records[-1]['serviceFallback'] = service_fallbacks[table].get(rid,
                            {'label': '', 'detail': 'No known player acquisition reference; retained for its overrides.'})
                    if table == 'Implant':
                        records[-1]['acquisition'] = acquisition['Implant'].get(rid, [])
                        records[-1]['serviceFallback'] = service_fallbacks['Implant'].get(rid,
                            {'label': '', 'detail': 'No known player acquisition reference; retained for its overrides.'})
                    if table == 'Item':
                        records[-1]['blueprintDrops'] = blueprint_refs['Item'].get(rid, [])
                        records[-1]['serviceFallback'] = service_fallbacks['Item'].get(rid,
                            {'label': '', 'detail': 'No known item loot or blueprint drop reference.'})
                    if table == 'Rule' and rid in ENEMY_RULES:
                        records[-1]['owner'] = 'Enemy Balance'
                raw = {r[TABLE_KEYS[table]]: r for r in rows}
                records.sort(key=lambda r: (tuple(effective(doc, table, raw[r['id']], c)
                                                  for c in LEADING_COLUMNS), natural(r['name']))
                             if table in ('Weapon', 'WeaponMod', 'Implant', 'Item') else ((), natural(r['name'])))
                result_grid = {'table': table, 'title': title, 'columns': visible, 'advanced': advanced, 'rows': records,
                               'multipliers': doc.get('implantMultipliers', {}) if table == 'Implant' else {}}
                if table in ('Weapon', 'WeaponMod', 'Implant', 'Item'):
                    result_grid['defaultSort'] = {'key': 'column:Cost', 'descending': False}
                if table in ('Weapon', 'WeaponMod'):
                    result_grid['dynamicColumns'] = True
                if table in ('Weapon', 'WeaponMod', 'Item'):
                    result_grid['blueprintColumn'] = {'label': 'Blueprint',
                        'empty': 'No blueprint drop reference in the selected database.'}
                if table in services:
                    result_grid['serviceColumn'] = {'name': 'ServiceOptionId', 'options': services[table],
                                                    'fallbackNonpositive': True, 'fallbackUnavailable': table in ('Implant', 'Item')}
                return result_grid

            def joined_grid(base_table, rows, title, base_heading, links, owners, blocks, hidden=()):
                joined = grid(base_table, rows, title)
                joined['joined'] = True
                for column in joined['columns'] + joined['advanced']:
                    column['group'] = column.get('group') or base_heading
                for record in joined['rows']:
                    record['targets'] = {column['name']: {'table': base_table, 'id': record['id'], 'column': column['name']}
                                         for column in joined['columns'] + joined['advanced']}
                    record['links'] = links[record['id']]['ids']
                offset = max((c['order'] for c in joined['columns'] + joined['advanced']), default=0) + 1
                for heading, table in blocks:
                    targets = {r[TABLE_KEYS[base_table]]: links[r[TABLE_KEYS[base_table]]][heading] for r in rows}
                    unique = {r[TABLE_KEYS[table]]: r for r in targets.values() if r}
                    if not unique:
                        continue
                    policy = 'varying' if base_table == 'Weapon' and table == 'Talent' else 'nonzero'
                    donor = grid(table, list(unique.values()), heading, policy)
                    for visibility in ('columns', 'advanced'):
                        for column in donor[visibility]:
                            if (table, column['name']) in hidden:
                                continue
                            name = heading + '.' + column['name']
                            joined[visibility].append(dict(column, name=name, group=heading, leading=False,
                                                           order=offset + column['order']))
                            for record in joined['rows']:
                                target = targets[record['id']]
                                record['baseline'][name] = target[column['name']] if target else None
                                if target:
                                    target_id = target[TABLE_KEYS[table]]
                                    shared = owners.get((table, target_id), {})
                                    record['targets'][name] = {'table': table, 'id': target_id, 'column': column['name'],
                                        'readOnly': target_id in protected.get(table, set()),
                                        'readOnlyReason': 'Managed by Hard Mode Fatigue / limit-break traits',
                                        'sharedWith': [n for i, n in shared.items() if i != record['id']]}
                    offset += max((c['order'] for c in donor['columns'] + donor['advanced']), default=0) + 1
                warnings = list(dict.fromkeys(w for row in rows for w in links[row[TABLE_KEYS[base_table]]]['warnings']))
                joined['joinsComplete'] = not warnings
                if warnings:
                    joined['warning'] = '; '.join(warnings)
                return joined

            def linked(rows, field, table, title, related=False, owner_name='TraitName'):
                ids = {r.get(field) for r in rows} - {None, '', '0', '-1'}
                missing = ids - allrows[table].keys()
                result_grid = grid(table, [allrows[table][i] for i in ids if i in allrows[table]], title, 'nonzero') if ids else None
                if missing and result_grid is not None:
                    result_grid['warning'] = 'Official data has unresolved %s pointers: %s' % (field, ', '.join(sorted(missing)))
                if related and result_grid:
                    for record in result_grid['rows']:
                        owners = sorted((r for r in rows if r.get(field) == record['id']),
                                        key=lambda r: natural(r[owner_name]))
                        record['section'] = ', '.join(dict.fromkeys(r[owner_name] for r in owners))
                        if owner_name == 'TraitName' and record['name'].startswith(('Effect.Name.', 'MatrixEffect.Name.')):
                            record['name'] = 'Level ' + ', '.join(sorted({r['TraitLevel'] for r in owners}, key=int))
                    result_grid['rows'].sort(key=lambda r: (natural(r['section']), natural(r['name'])))
                return result_grid

            def page(pid, title, group, grids, **kwargs):
                for g in grids:
                    if g and group in ('Weapons', 'Drone weapons', 'Consumables', 'Cyberware', 'Cyberware modules'):
                        g['scrollWithPage'] = True
                result['pages'].append({'id': pid, 'title': title, 'group': group,
                                        'grids': [g for g in grids if g and (g['rows'] or g.get('warning'))], **kwargs})

            enemy_weapons = _effective_enemy_ids(source, config_dir, 'WeaponTypeId')
            # Workshop SQL changes official rows even when Hard Mode has
            # repointed its local enemies to cloned weapons.
            official_enemy_weapons = {r['WeaponTypeId'] for r in source.read('MonsterTypeModel')[1]}
            enemy_weapons.update(official_enemy_weapons)
            weapons = [r for r in allrows['Weapon'].values() if r['WeaponId'] in acquisition['Weapon']]
            classes = {int(r['WeaponClass']) for r in weapons}
            order = WEAPON_ORDER + sorted(classes - set(WEAPON_ORDER) - DRONE_CLASSES) + sorted(classes & DRONE_CLASSES)
            rules = special_rules(source)
            for cls in (c for c in order if c in classes):
                rows = [r for r in weapons if int(r['WeaponClass']) == cls]
                talents = [r for r in allrows['Talent'].values() if r.get('Weapon') in {w['WeaponId'] for w in rows}]
                names = {r.get('WeaponClassName', '') for r in rows
                         if r.get('WeaponClassName') and not r['WeaponClassName'].startswith('Gear.')}
                title = CLASS_NAMES.get(cls, next(iter(names)) if len(names) == 1 else 'Weapon class %s' % cls)
                if cls in (16, 17):
                    weapon_links, weapon_owners, blocks = cyberweapon_links(allrows, doc, rows)
                    weapon_grid = joined_grid('Weapon', rows, title, 'Weapon', weapon_links, weapon_owners, blocks,
                                              hidden={('Talent', 'Range')} if cls == 16 else ())
                    weapon_grid['serviceColumn'] = {'name': 'ServiceOptionId', 'options': services['Implant'],
                                                    'source': 'cyberware', 'readOnly': True}
                    for record in weapon_grid['rows']:
                        record['cyberwareServices'] = [
                            {'id': i['ImplantTypeId'], 'name': i['ImplantName'], 'baseline': i['ServiceOptionId'],
                             'serviceFallback': service_fallbacks['Implant'].get(i['ImplantTypeId'], {'label': '', 'detail': ''})}
                            for i in sorted(weapon_links[record['id']]['implants'].values(),
                                            key=lambda i: natural(i['ImplantName']))]
                        if record['cyberwareServices']:
                            record['weaponName'] = record['name']
                            record['name'] = ' / '.join(dict.fromkeys(i['name'] for i in record['cyberwareServices']))
                    cost_implants = {i['ImplantTypeId']: i for linked in weapon_links.values()
                                     if len(linked['implants']) == 1 for i in linked['implants'].values()}
                    cost_grid = grid('Implant', list(cost_implants.values()), 'Cyberware cost')
                    cost_column = next(c for c in weapon_grid['columns'] + weapon_grid['advanced'] if c['name'] == 'Cost')
                    for columns in ('columns', 'advanced'):
                        weapon_grid[columns] = [c for c in weapon_grid[columns] if c['name'] != 'Cost']
                    if cost_grid:
                        donor = next(c for c in cost_grid['columns'] + cost_grid['advanced'] if c['name'] == 'Cost')
                        cost_column.update(integer=donor['integer'], visibilityPolicy=donor['visibilityPolicy'])
                    cost_column['group'] = 'Cyberware'
                    visible = cost_grid and any(c['name'] == 'Cost' for c in cost_grid['columns'])
                    weapon_grid['columns' if visible else 'advanced'].append(cost_column)
                    for columns in ('columns', 'advanced'):
                        weapon_grid[columns].sort(key=lambda c: c['order'])
                    for record in weapon_grid['rows']:
                        implants = weapon_links[record['id']]['implants']
                        record['baseline']['Cost'] = None
                        record['targets'].pop('Cost', None)
                        if len(implants) == 1:
                            iid, implant = next(iter(implants.items()))
                            record['baseline']['Cost'] = implant['Cost']
                            record['targets']['Cost'] = {'table': 'Implant', 'id': iid, 'column': 'Cost',
                                'readOnly': iid in protected.get('Implant', set()),
                                'sharedWith': [r['name'] for r in weapon_grid['rows'] if r['id'] != record['id']
                                               and iid in weapon_links[r['id']]['implants']]}
                        else:
                            warning = 'Weapon %s: Cost requires one linked implant; found %s.' % (record['id'], len(implants))
                            weapon_grid['warning'] = '; '.join(filter(None, (weapon_grid.get('warning'), warning)))
                            weapon_grid['joinsComplete'] = False
                    def cyber_order(record):
                        targets = [record['targets'].get(c) for c in LEADING_COLUMNS]
                        return (tuple(effective(doc, t['table'], allrows[t['table']][t['id']], t['column'])
                                      if t else float('inf') for t in targets), natural(record['name']))
                    weapon_grid['rows'].sort(key=cyber_order)
                else:
                    weapon_grid = grid('Weapon', rows, 'Weapon stats')
                for record in weapon_grid['rows']:
                    record['enemyUse'] = record['id'] in enemy_weapons
                weapon_grid['specialRuleColumn'] = 'SpecialRule'
                if cls in (1, 10):
                    pool = [r for r in allrows['Weapon'].values() if r['WeaponClass'] == str(cls)]
                    weapon_grid['iconSource'] = asset_picker('Weapon', rows, pool, assets, doc)
                    weapon_grid['iconSource']['regroup'] = True
                    weapon_grid['iconColumn'] = True
                    for record in weapon_grid['rows']:
                        asset_id = allrows['Weapon'][record['id']]['Asset3DTypeId']
                        path = assets.get(asset_id, {}).get('Thumbnail', '')
                        # This is the actual official thumbnail reference, not
                        # a weapon-name heuristic or an invented subtype.
                        icon = path.rsplit('/', 1)[-1]
                        record['icon'] = label(re.sub(r'^W_(Melee|Pistol)_', '', icon).replace('_', ' ')) or 'Asset ' + asset_id
                        record['iconPath'] = path
                        record['section'] = record['icon']
                    weapon_grid['rows'].sort(key=lambda r: natural(r['icon']))
                if cls in (3, 4, 12):
                    pool = [r for r in allrows['Weapon'].values() if r['WeaponClass'] == str(cls)]
                    weapon_grid['iconColumn'] = True
                    weapon_grid['iconEditor'] = asset_picker('Weapon', rows, pool, assets, doc)
                    for column_set in ('columns', 'advanced'):
                        weapon_grid[column_set] = [c for c in weapon_grid[column_set] if c['name'] != 'Asset3DTypeId']
                page('weapon-%s' % cls, title, 'Drone weapons' if cls in DRONE_CLASSES else 'Weapons', [weapon_grid,
                     grid('Talent', talents, 'Attacks', 'varying') if talents and cls not in (16, 17) else None], specialRules=rules)

            class_mods = source.read('WeaponClassModModel')[1]
            mod_groups = {}
            mod_visual_pools = {}
            unresolved_mods = []
            for row in allrows['WeaponMod'].values():
                fit = mod_fitment(source, row, class_mods)
                mod_visual_pools.setdefault((fit['category'], fit['title']), []).append(row)
                if row['WeaponModId'] not in acquisition['WeaponMod']:
                    continue
                if not fit['declared'] and not fit['mapped']:
                    unresolved_mods.append({'id': row['WeaponModId'], 'modClass': fit['modClass'],
                                            'slot': fit['slot'], 'reason': 'No weapon-class mapping or localization'})
                mod_groups.setdefault((fit['category'], fit['title']), []).append((row, fit))
            mod_grids = []
            for (category, title), members in sorted(mod_groups.items(),
                    key=lambda item: (MOD_CATEGORIES.index(item[0][0]), natural(item[0][1]))):
                g = grid('WeaponMod', [r for r, _ in members], 'Weapon mods')
                g.update(key='mods-' + '-'.join(r['WeaponModId'] for r, _ in members),
                         category=category, subsection=title)
                fits = {r['WeaponModId']: f for r, f in members}
                editor = asset_picker('WeaponMod', [r for r, _ in members], mod_visual_pools[category, title],
                                      assets, doc, swap_scope=any(f['modClass'] == '6' for _, f in members),
                                      multiple_only=False)
                if len({c['thumbnail'] for c in editor['choices']}) > 1:
                    g['iconEditor'] = editor
                    for column_set in ('columns', 'advanced'):
                        g[column_set] = [c for c in g[column_set] if c['name'] != 'Asset3DTypeId']
                else:
                    g['iconSource'] = editor
                for record in g['rows']:
                    fit = fits[record['id']]
                    record['fitment'] = title
                    record['fitmentSource'] = '%s · ModClassId %s · ModSlot %s' % (fit['key'], fit['modClass'], fit['slot'])
                    asset_id = str(int(effective(doc, 'WeaponMod', allrows['WeaponMod'][record['id']], 'Asset3DTypeId')))
                    path = assets.get(asset_id, {}).get('Thumbnail', '')
                    token = path.rsplit('/', 1)[-1]
                    record['icon'] = label(re.sub(r'^(WeaponMod_|weapon_mod_)', '', token).replace('_', ' ')) or 'No icon'
                    record['iconPath'] = path
                    record['section'] = record['icon']
                    record['sectionKey'] = path or 'Asset ' + asset_id
                    record['iconOrder'] = editor['assets'].get(asset_id, {}).get('order', 0) if editor else 0
                g['iconColumn'] = True
                g['rows'].sort(key=lambda r: (r['iconOrder'], natural(r['icon']), natural(r['sectionKey'])))
                mod_grids.append(g)
            page('weapon-mods', 'Weapon mods', 'Weapons', mod_grids, unresolvedMods=unresolved_mods,
                 iconHelp='Choose a visual for fitments with multiple graphics. Mods move to the selected icon group. The first choice restores the official visual. Save, then export to Modkit to apply your changes.')
            other_grids = []
            for table, title in (('Weapon', 'Other weapons'), ('WeaponMod', 'Other weapon mods')):
                records = [r for rid, r in allrows[table].items() if rid not in acquisition[table]
                           and any(adjustment(v) is not None for v in doc['tables'].get(table, {}).get(rid, {}).values())]
                if records:
                    g = grid(table, records, title)
                    if table == 'Weapon':
                        for record in g['rows']:
                            record['enemyUse'] = record['id'] in enemy_weapons
                    other_grids.append(g)
            if other_grids:
                page('other-weapon-overrides', 'Other weapon overrides', 'Weapons', other_grids,
                     description='These records have no known player acquisition reference. They remain here while they have overrides. Clear their overrides and save to remove them from this page.')
            item_editors = consumable_editors(source, allrows, assets, doc, item_owners)
            item_classes = {int(r['ItemClass']) for r in allrows['Item'].values()}
            item_classes.update(int(effective(doc, 'Item', r, 'ItemClass')) for r in allrows['Item'].values())
            for cls in sorted(item_classes):
                items = [r for r in allrows['Item'].values() if int(effective(doc, 'Item', r, 'ItemClass')) == cls]
                title = ITEM_CLASSES.get(cls, 'Item class %s' % cls)
                if not items:
                    page('consumable-%s' % cls, title, 'Consumables', [], description='No items currently use this tag.')
                    continue
                separate_effects = any(len({item_links[r['ItemTypeId']]['ids'][name]
                                            for name in ('Self effect', 'Target effect')} - {'0', '-1', ''}) > 1 for r in items)
                blocks = [('Action', 'Talent')]
                blocks += [('Self effect', 'Effect'), ('Target effect', 'Effect')] if separate_effects else [('Effects', 'Effect')]
                blocks += [('Matrix effects', 'MatrixEffect')]
                item_grid = joined_grid('Item', items, title, 'Item', item_links, item_owners, blocks)
                item_grid['consumableEditor'] = item_editors['controls']
                for columns in ('columns', 'advanced'):
                    item_grid[columns] = [c for c in item_grid[columns] if c['name'] not in
                        ('ItemClass', 'Asset3DTypeId', 'Action.ExtraAsset')]
                for record in item_grid['rows']:
                    record['consumable'] = item_editors['rows'][record['id']]
                page('consumable-%s' % cls, title, 'Consumables', [item_grid])
            page('implant-global', 'All cyberware', 'Cyberware', [], multipliers=MULTIPLIERS)
            player_implants = [r for r in allrows['Implant'].values() if r['ImplantTypeId'] in acquisition['Implant']]
            for slot in sorted({int(r['ImplantSlot']) for r in player_implants},
                               key=lambda s: (SLOT_ORDER.index(s) if s in SLOT_ORDER else len(SLOT_ORDER), s)):
                rows = [r for r in player_implants if int(r['ImplantSlot']) == slot]
                title = SLOT_NAMES.get(slot, 'Module slot %s' % slot)
                page('implant-%s' % slot, title, 'Cyberware modules' if slot >= 100 else 'Cyberware',
                     [joined_grid('Implant', rows, title, 'Implant', cyberware_links, implant_owners,
                                  [('Effects', 'Effect'), ('Matrix effects', 'MatrixEffect')])])
            def implant_has_overrides(row):
                rid = row['ImplantTypeId']
                linked = cyberware_links[rid]
                targets = [('Implant', rid)] + [(table, linked['ids'][heading])
                    for heading, table in (('Effects', 'Effect'), ('Matrix effects', 'MatrixEffect'))
                    if linked[heading] is not None]
                return any(adjustment(value) is not None for table, target in targets
                           for value in doc['tables'].get(table, {}).get(target, {}).values())
            other_implants = [r for r in allrows['Implant'].values()
                              if r['ImplantTypeId'] not in acquisition['Implant'] and implant_has_overrides(r)]
            if other_implants:
                page('other-cyberware-overrides', 'Other cyberware overrides', 'Cyberware',
                     [joined_grid('Implant', other_implants, 'Other cyberware', 'Implant', cyberware_links,
                                  implant_owners, [('Effects', 'Effect'), ('Matrix effects', 'MatrixEffect')])],
                     description='These implants have no known player acquisition reference under the inclusive filter. '
                                 'They remain here while the implant or its linked effects have overrides. '
                                 'Clear those overrides and save to remove them from this page.')
            face_actions = {}
            for talent in allrows['Talent'].values():
                if talent['TalentIsFace'] != '0' and talent['TargetType'] == 'LEVERAGE':
                    face_actions.setdefault(talent['ActionId'], []).append(talent['TalentName'])
            leverage_groups = {name: [] for name in ('Face leverage', '0-token leverage', 'Matrix-only leverage',
                                                    'Favor-cost leverage', 'Other leverage')}
            for row in allrows['MissionAdvantage'].values():
                heading = ('Face leverage' if row['AdvantageTypeId'] in face_actions else
                           '0-token leverage' if effective(doc, 'MissionAdvantage', row, 'TokenCost') == 0 else
                           'Matrix-only leverage' if effective(doc, 'MissionAdvantage', row, 'AdvantageIsMatrixOnly') != 0 else
                           'Favor-cost leverage' if effective(doc, 'MissionAdvantage', row, 'FavorCost') != 0 else
                           'Other leverage')
                leverage_groups[heading].append(row)
            leverage_grids = []
            for heading, rows in leverage_groups.items():
                if not rows:
                    continue
                g = grid('MissionAdvantage', rows, 'Leverage', 'nonzero')
                g.update(key=heading, subsection=heading, subsectionOpen=heading == 'Other leverage')
                for record in g['rows']:
                    if record['id'] in face_actions:
                        record['description'] = ', '.join(sorted(face_actions[record['id']]))
                leverage_grids.append(g)
            page('leverage', 'Leverage', 'Character', leverage_grids)
            rows = list(allrows['Trait'].values())
            trait_grids = []
            knight_groups = knight_trait_groups(source)
            knight_rows = [r for r in rows if r['TraitGroup'] in knight_groups]
            other_rows = [r for r in rows if r['TraitGroup'] not in knight_groups]
            trait_sections = [('Cyber Knight Traits', knight_rows)] if knight_rows else []
            for score in sorted({effective(doc, 'Trait', r, 'TraitScore') for r in other_rows}):
                trait_sections.append(('Trait score %s' % (format(score, '+g') if score else '0'),
                                       [r for r in other_rows if effective(doc, 'Trait', r, 'TraitScore') == score]))
            for heading, subset in trait_sections:
                for g in (grid('Trait', subset, 'Traits', 'nonzero'),
                          linked(subset, 'EffectTypeId', 'Effect', 'Effects', related=True),
                          linked(subset, 'MatrixEffectTypeId', 'MatrixEffect', 'Matrix effects', related=True)):
                    if g:
                        g['subsection'] = heading
                        g['key'] = '%s:%s' % (g['table'], heading)
                        trait_grids.append(g)
            page('traits', 'Traits', 'Character', trait_grids, knightTraitEvidence=knight_groups)
            rule_grids = []
            for group in sorted({r['GroupId'] for r in allrows['Rule'].values()}):
                g = grid('Rule', [r for r in allrows['Rule'].values() if r['GroupId'] == group and r['RuleId'] not in STANDALONE_RULES], 'Rules', 'all')
                g.update(key='rules-' + group, subsection='Power level' if group == 'POWERLEVEL' else group.replace('_', ' ').title())
                rule_grids.append(g)
            page('rules', 'Rules', 'Player Balance', rule_grids)
    except (ValueError, OSError, static_data.DataError) as exc:
        result['error'] = str(exc)
        result['pages'] = []
    return result


def apply_edits(doc, edits, source, config_dir=None):
    result = copy.deepcopy(doc)
    for col, value in edits.get('implantMultipliers', {}).items():
        result.setdefault('implantMultipliers', {})[col] = value
    for cell in edits.get('cells', []):
        table, rid, col = cell['table'], str(cell['id']), cell['column']
        literal = col in TEXT_FIELDS.get(table, set())
        value = str(cell.get('value', '')).strip() if literal else normalize_adjustment(cell.get('value', ''))
        fields = result['tables'].setdefault(table, {}).setdefault(rid, {})
        if value:
            if not literal:
                adjustment(value)
            fields[col] = value
        else:
            fields.pop(col, None)
        if not fields:
            result['tables'][table].pop(rid)
        if not result['tables'][table]:
            result['tables'].pop(table)
    validate(result, source, config_dir)
    return result


def rounded(expression):
    """SQLite expression matching Math.Round's ties-to-even integer write."""
    trunc = 'CAST((%s) AS INTEGER)' % expression
    return ('CASE WHEN abs((%s)-%s)=0.5 THEN %s + (abs(%s) %% 2) * '
            'CASE WHEN (%s)<0 THEN -1 ELSE 1 END ELSE CAST(round(%s) AS INTEGER) END'
            % (expression, trunc, trunc, trunc, expression, expression))


def sql(doc, source, config_dir=None):
    validate(doc, source, config_dir)
    statements, touched = [], set()
    for table, records in sorted(doc['tables'].items()):
        columns = declarations(source, table)
        for rid, fields in sorted(records.items(), key=lambda x: int(x[0])):
            assignments = []
            for col, value in sorted(fields.items()):
                if col in TEXT_FIELDS.get(table, set()):
                    if value:
                        assignments.append('%s=\'%s\'' % (static_data.quote(col), value.replace("'", "''")))
                        touched.add((table, rid, col))
                    continue
                parsed = adjustment(value)
                if parsed is None:
                    continue
                op, number = parsed
                expr = format(number, '.15g')
                if op != 'set':
                    operand = static_data.quote(col)
                    if 'INT' in columns[col].upper():
                        operand = '(' + rounded(operand) + ')'
                    expr = '%s %s (%s)' % (operand, '*' if op == 'multiply' else '+', expr)
                if 'INT' in columns[col].upper():
                    expr = rounded(expr)
                assignments.append('%s=%s' % (static_data.quote(col), expr))
                touched.add((table, rid, col))
            if assignments:
                statements.append('UPDATE %s SET %s WHERE %s=%d;' %
                                  (static_data.quote(table), ', '.join(assignments),
                                   static_data.quote(TABLE_KEYS[table]), int(rid)))
    global_assignments = []
    for col in MULTIPLIERS:
        value = doc.get('implantMultipliers', {}).get(col, 1)
        if value != 1:
            expr = rounded('(%s) * %s' % (rounded(static_data.quote(col)), format(value, '.15g')))
            global_assignments.append('%s=%s' % (static_data.quote(col), expr))
    if global_assignments:
        # Deliberately unscoped: includes every implant/module, even future rows.
        statements.append('UPDATE "Implant" SET %s;' % ', '.join(global_assignments))
    return statements, touched


def augment(data, provenance, config_dir, database):
    """Append Workshop data without modifying the native talent assignments."""
    payload, receipt = json.loads(data), json.loads(provenance)
    doc = load(config_dir)
    with static_data.StaticData(database) as source:
        statements, touched = sql(doc, source, config_dir)
        receipt['official_database'] = identity(source)
    # RawSQL runs after native table records in the installed parser. Overlap
    # would silently choose an owner, so refuse instead.
    aliases = {'Talent': {'AP': 'ApCost', 'Charges': 'MaxCharges', 'Recharge': 'RechargeTurns',
                         'AoE': 'RangeAoE', 'TargetDuration': 'TargetEffectDuration'},
               'Effect': {'MoveDebuff': 'MoveSpeedDebuff', 'HealType': 'EffectHealType'}}
    for table, key in TABLE_KEYS.items():
        for row in payload.get(table, []):
            for col in row:
                if (table, str(row[key]), aliases.get(table, {}).get(col, col)) in touched:
                    raise ValueError('Talent and player tuning both own %s %s %s' % (table, row[key], col))
    payload['RawSQL'] = statements
    data = encode(payload)
    receipt['scope'] = 'player talents, weapons, cyberware, consumables, leverage, traits and rules (excluding Enemy Balance Rule 82 and standalone Rules 83-85)'
    receipt['parser_source']['sha256'] = hashlib.sha256(data).hexdigest()
    receipt['player_balance'] = {'source': FILE, 'sha256': hashlib.sha256((Path(config_dir) / FILE).read_bytes()).hexdigest(),
                                 'statements': len(statements), 'assignments': len(touched)}
    return data, encode(receipt), receipt


def import_legacy(config_dir):
    """Explicit one-time transfer; caller guards and commits the whole batch."""
    import cyberweapons
    import implants
    root = Path(config_dir) / 'ckf.hardmode.d'
    doc = empty()
    global_doc = json.loads((root / 'implants-global.json').read_text(encoding='utf-8-sig'))
    for col, old in [('Cost', 'costMultiply'), ('InstallTime', 'installTimeMultiply'), ('ImplantStress', 'implantStressMultiply')]:
        doc['implantMultipliers'][col] = global_doc[old]

    def add(table, rid, column, value):
        # Legacy -N means subtraction; Workshop -N is an absolute value.
        # Preserve imported arithmetic explicitly as +-N.
        if str(value).strip().startswith('-'):
            value = '+' + str(value).strip()
        value = normalize_adjustment(value)
        fields = doc['tables'].setdefault(table, {}).setdefault(str(rid), {})
        if column in fields and fields[column] != value:
            raise ValueError('Conflicting legacy edits to %s %s %s' % (table, rid, column))
        fields[column] = value

    for path in sorted(root.glob('implants-slot*.csv')):
        for row in csv_rows(path):
            for col, value in row.items():
                if col.startswith('_') or col in implants.IMPLANT_IDENTITY or not value:
                    continue
                table, key = ('Implant', 'ImplantTypeId') if col in implants.IMPLANT_LEVERS else ('Effect', 'ImplantEffectId')
                add(table, row[key], col, value)
    for filename, mapping in [('cyberweapons-lasers.csv', cyberweapons.LASER_MAP), ('cyberweapons-claws.csv', cyberweapons.CLAW_MAP)]:
        for row in csv_rows(root / filename):
            for col, (model, target) in mapping:
                if row.get(col):
                    add(model.removesuffix('Model'), row['WeaponId' if model == 'WeaponModel' else 'TalentId'], target, row[col])
    add('Rule', 22, 'Value', '15')
    return doc
