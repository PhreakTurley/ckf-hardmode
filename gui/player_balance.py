"""Workshop-owned player tuning and fresh official-data catalogs.

Only sparse adjustments live in config. Catalog rows, joins and numeric
declarations are read from Official/data.db on every request. No save database
is opened. SQL is emitted in the same order as the former implant rules:
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
# ContactService.ServiceFlow scopes the option id: for example the official
# ContactService rows 1, 4 and 7 use option 1 for different catalogs.
SERVICE_FLOWS = {'Weapon': '1', 'WeaponMod': '3', 'Item': '7', 'Implant': '8'}
LABELS = {'ApCost': 'AP cost', 'CritMultiBase': 'Crit damage', 'CritMultiStealth': 'Stealth crit damage',
          'ImplantStress': 'Stress', 'InstallTime': 'Install time', 'BaseCost': 'Price',
          'BallisticDamage1': 'Ballistic · 1', 'BallisticDamage2': 'Ballistic · 2',
          'PhysicalDamage1': 'Physical · 1', 'PhysicalDamage2': 'Physical · 2',
          'PureDamage1': 'Pure · 1', 'PureDamage2': 'Pure · 2',
          'ActionPoints1': 'AP · 1', 'ActionPoints2': 'AP · 2',
          'Accuracy1': 'Accuracy · 1', 'Accuracy2': 'Accuracy · 2',
          'TargetEffectDuration': 'Target duration', 'RechargeTurns': 'Recharge',
          'MaxCharges': 'Charges', 'EffectTypeId': 'Effect', 'MatrixEffectTypeId': 'Matrix effect'}
CLASS_NAMES = {1: 'Melee', 2: 'Pistol', 3: 'AR', 4: 'Shotgun',
               5: 'E-Rifle', 6: 'Sniper Rifle', 7: 'Canine Attack Rig', 9: 'Drone assault rifles',
               10: 'SMG', 11: 'Revolver', 12: 'UAR', 14: 'Railgun',
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
            any(t in r[2].upper() for t in ('INT', 'REAL', 'NUM', 'FLOAT', 'DOUBLE'))}


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
                    raise ValueError('%s.%s is no longer a numeric content field' % (table, col))
                parsed = adjustment(value)
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


def player_weapon_references(source):
    """Positive player-content references; absence is not proof of enemy use.

    BlueprintClass.Weapon=1 is declared in CoreRPG_v1.dll; LootTypes.Weapon=8
    is captured in sheets/raw/_id_constants.csv (LootTypes, Weapon).
    Keep the table/type with the id: OutputId/LootKey alone can refer to
    several different content tables. An unavailable, non-lootable blueprint
    alone is not sufficient evidence of player availability.
    """
    services = {r['ServiceOptionId'] for r in source.read('ContactServiceModel', ('ServiceOptionId',))[1]
                if int(r['ServiceOptionId']) > 0}
    refs = {r['WeaponId'] for r in source.read('WeaponModel')[1]
            if r['ServiceOptionId'] in services}
    refs.update(r['OutputId'] for r in source.read('BlueprintModel', ('OutputId', 'BlueprintClassId', 'Lootable'))[1]
                if r['BlueprintClassId'] == '1' and r['Lootable'] == '1')
    refs.update(r['LootKey'] for r in source.read('MissionLootModel', ('LootKey', 'LootTypeId'))[1]
                if r['LootTypeId'] == '8')
    refs.update(r['Weapon'] for r in source.read('TalentModel')[1]
                if r['TalentIsCyber'] == '1')
    for row in source.read('DroneChassisModel')[1]:
        refs.update((row['WeaponType1'], row['WeaponType2']))
    refs.update(r['Weapon'] for r in source.read('DronePrebuiltModel')[1])
    return refs - {'', '0', '-1'}


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
    if not slot_match or int(modclass) >= 100:
        title += ' · slot ' + slot
    return {'title': title, 'key': key, 'declared': declared,
            'slot': slot, 'modClass': modclass, 'excluded': sorted(excluded),
            'mapped': bool(classes)}


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
    for row in source.read('ContactServiceModel')[1]:
        for table, flow in SERVICE_FLOWS.items():
            if row['ServiceFlow'] != flow:
                continue
            key = 'ContactService.Name.' + row['ServiceTypeId']
            name = source.locale.get(key, key)
            text = name + (' · L' + row['DisplayLevel'] if int(row['DisplayLevel']) > 0 else '')
            entry = grouped[table].setdefault(row['ServiceOptionId'], {'labels': [], 'references': []})
            if text not in entry['labels']:
                entry['labels'].append(text)
            entry['references'].append({'id': row['ServiceTypeId'], 'flow': flow,
                                        'level': row['ServiceLevel'], 'displayLevel': row['DisplayLevel'], 'locale': key})
    return {table: {option: {'label': ', '.join(entry['labels']), 'references': entry['references'],
                            'detail': 'ServiceOptionId %s; ServiceFlow %s; ContactService %s' %
                                      (option, SERVICE_FLOWS[table], ', '.join(r['id'] for r in entry['references']))}
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


def catalog(config_dir, database):
    """Build rows and visible columns from a fresh, complete official read."""
    try:
        doc = load(config_dir)
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
                    values = {r.get(col, '') for r in rows}
                    has_override = any(overrides.get(r[TABLE_KEYS[table]], {}).get(col, '') != '' for r in rows)
                    interesting = policy == 'all' or (len(values) > 1 if policy == 'varying'
                                   else any(v not in ('', '0', '0.0') for v in values))
                    target = visible if has_override or (interesting and col not in METADATA) else advanced
                    target.append({'name': col, 'label': label(col), **column_presentation(table, col)})
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
                    if table == 'Rule' and rid in ENEMY_RULES:
                        records[-1]['owner'] = 'Enemy Balance'
                raw = {r[TABLE_KEYS[table]]: r for r in rows}
                records.sort(key=lambda r: (tuple(effective(doc, table, raw[r['id']], c)
                                                  for c in LEADING_COLUMNS), natural(r['name']))
                             if table in ('Weapon', 'WeaponMod', 'Implant', 'Item') else ((), natural(r['name'])))
                result_grid = {'table': table, 'title': title, 'columns': visible, 'advanced': advanced, 'rows': records,
                               'multipliers': doc.get('implantMultipliers', {}) if table == 'Implant' else {}}
                if table in services:
                    result_grid['serviceColumn'] = {'name': 'ServiceOptionId', 'options': services[table]}
                return result_grid

            def joined_grid(base_table, rows, title, base_heading, links, owners, blocks):
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
                    donor = grid(table, list(unique.values()), heading, 'nonzero')
                    for visibility in ('columns', 'advanced'):
                        for column in donor[visibility]:
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
            player_refs = player_weapon_references(source)
            weapons = [r for r in allrows['Weapon'].values()
                       if r['WeaponId'] not in official_enemy_weapons or r['WeaponId'] in player_refs]
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
                    weapon_grid = joined_grid('Weapon', rows, title, 'Weapon', weapon_links, weapon_owners, blocks)
                    weapon_grid['cyberwareServiceColumn'] = {'options': services['Implant']}
                    for record in weapon_grid['rows']:
                        record['cyberwareServices'] = [
                            {'id': i['ImplantTypeId'], 'name': i['ImplantName'], 'baseline': i['ServiceOptionId']}
                            for i in weapon_links[record['id']]['implants'].values()]
                else:
                    weapon_grid = grid('Weapon', rows, 'Weapon stats')
                for record in weapon_grid['rows']:
                    record['enemyUse'] = record['id'] in enemy_weapons
                weapon_grid['specialRuleColumn'] = 'SpecialRule'
                if cls in (1, 10):
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
                if cls in (3, 4):
                    # Keep the pointer per weapon: editing the shared asset's
                    # Thumbnail would change every weapon referencing it.
                    choices = []
                    for asset_id, asset in assets.items():
                        owners = [r for r in allrows['Weapon'].values()
                                  if r['WeaponClass'] == str(cls) and r['Asset3DTypeId'] == asset_id]
                        if not owners or not asset['Thumbnail'] or not asset['Resource']:
                            continue
                        examples = [r for r in rows if r['Asset3DTypeId'] == asset_id] or owners
                        token = asset['Thumbnail'].rsplit('/', 1)[-1]
                        choices.append({'id': asset_id, 'name': label(re.sub(r'^W_(AR|Shotgun)_', '', token).replace('_', ' ')),
                                        'token': token, 'thumbnail': asset['Thumbnail'], 'resource': asset['Resource'],
                                        'examples': [r['WeaponName'] for r in examples[:3]]})
                    choices.sort(key=lambda c: natural(c['name']))
                    weapon_grid['iconColumn'] = True
                    weapon_grid['iconEditor'] = {'column': 'Asset3DTypeId', 'choices': choices,
                        'assets': {aid: {'token': a['Thumbnail'].rsplit('/', 1)[-1],
                                         'thumbnail': a['Thumbnail'], 'resource': a['Resource']}
                                   for aid, a in assets.items()}}
                    for column_set in ('columns', 'advanced'):
                        weapon_grid[column_set] = [c for c in weapon_grid[column_set] if c['name'] != 'Asset3DTypeId']
                page('weapon-%s' % cls, title, 'Drone weapons' if cls in DRONE_CLASSES else 'Weapons', [weapon_grid,
                     grid('Talent', talents, 'Attacks', 'varying') if talents and cls not in (16, 17) else None], specialRules=rules)

            class_mods = source.read('WeaponClassModModel')[1]
            mod_groups = {}
            unresolved_mods = []
            for row in allrows['WeaponMod'].values():
                fit = mod_fitment(source, row, class_mods)
                if not fit['declared'] and not fit['mapped']:
                    unresolved_mods.append({'id': row['WeaponModId'], 'modClass': fit['modClass'],
                                            'slot': fit['slot'], 'reason': 'No weapon-class mapping or localization'})
                    continue
                mod_groups.setdefault(fit['title'], []).append((row, fit))
            mod_grids = []
            for title, members in sorted(mod_groups.items(), key=lambda item: natural(item[0])):
                g = grid('WeaponMod', [r for r, _ in members], 'Weapon mods')
                g.update(key='mods-' + '-'.join(r['WeaponModId'] for r, _ in members), subsection=title)
                fits = {r['WeaponModId']: f for r, f in members}
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
                g['iconColumn'] = True
                g['rows'].sort(key=lambda r: natural(r['sectionKey']))
                mod_grids.append(g)
            page('weapon-mods', 'Weapon mods', 'Weapons', mod_grids, unresolvedMods=unresolved_mods)
            for cls in sorted({int(r['ItemClass']) for r in allrows['Item'].values()}):
                items = [r for r in allrows['Item'].values() if int(r['ItemClass']) == cls]
                title = ITEM_CLASSES.get(cls, 'Item class %s' % cls)
                separate_effects = any(len({item_links[r['ItemTypeId']]['ids'][name]
                                            for name in ('Self effect', 'Target effect')} - {'0', '-1', ''}) > 1 for r in items)
                blocks = [('Action', 'Talent')]
                blocks += [('Self effect', 'Effect'), ('Target effect', 'Effect')] if separate_effects else [('Effects', 'Effect')]
                blocks += [('Matrix effects', 'MatrixEffect')]
                page('consumable-%s' % cls, title, 'Consumables',
                     [joined_grid('Item', items, title, 'Item', item_links, item_owners, blocks)])
            page('implant-global', 'All cyberware', 'Cyberware', [], multipliers=MULTIPLIERS)
            for slot in sorted({int(r['ImplantSlot']) for r in allrows['Implant'].values()},
                               key=lambda s: (SLOT_ORDER.index(s) if s in SLOT_ORDER else len(SLOT_ORDER), s)):
                rows = [r for r in allrows['Implant'].values() if int(r['ImplantSlot']) == slot]
                title = SLOT_NAMES.get(slot, 'Module slot %s' % slot)
                page('implant-%s' % slot, title, 'Cyberware modules' if slot >= 100 else 'Cyberware',
                     [joined_grid('Implant', rows, title, 'Implant', cyberware_links, implant_owners,
                                  [('Effects', 'Effect'), ('Matrix effects', 'MatrixEffect')])])
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
        value = normalize_adjustment(cell.get('value', ''))
        fields = result['tables'].setdefault(table, {}).setdefault(rid, {})
        if value:
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
