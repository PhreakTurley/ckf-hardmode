"""Build the additive Hire Everyone Workshop data mod from Official content.

Only content SQL is prepared/installed. No game process or campaign is opened.
The installed Modkit parser and an independent in-memory SQL check run first.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'gui')]
from static_data import StaticData, DEFAULT_DB, quote
from modkit import commit_files, state, prepare_parser

MODKIT = Path(r'C:\Program Files (x86)\Steam\steamapps\common\Cyber Knights Mod Uploader')
UPLOADER = MODKIT / 'WorkshopContent/HireEveryone'
WORKSHOP = MODKIT.parents[1] / 'workshop/content/1021210/3841540859'
PROJECT = ROOT / 'ckf-hire-everyone'
PREFIX = 'HE3841540859'
BASE = 384154000
# Authored scope: the available Hub roster, excluding four unfinished entries
# whose shipped blocks have Pre_AlwaysFail. New official entries require review.
HUB = (4000, 4003, 4004, 4005, 4006, 4008, 4009, 4011, 4012,
       4013, 4014, 4015, 4016, 305000, 305100)
STARTERS = (14, 18, 19, 20, 22, 23, 24, 25, 28, 33, 35, 38)
SLOTS = {13: 4, 19: 4, 12: 3, 5: 3, 2: 5, 3: 5, 7: 5, 11: 5, 14: 5, 15: 5}
GROUPS = {13: 'Hackers', 19: 'Wireghosts', 12: 'Vanguards', 5: 'AgentEXs',
          2: 'Warmachines', 3: 'Cyberswords', 7: 'Soldiers', 11: 'Snipers',
          14: 'Gunslingers', 15: 'Scourges'}
KEYS = {'Backstory': 'BackstoryId', 'Block': 'Id',
        'BlockCondition': 'BlockConditionId', 'StoryNode': 'NodeId'}


def encode(value):
    return (json.dumps(value, indent=2, ensure_ascii=False) + '\n').encode('utf-8')


def literal(value):
    if value is None:
        return 'NULL'
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def build(database):
    with StaticData(database) as data:
        columns = {t: [c[1] for c in data.schema[t] if not c[5]] for t in KEYS}
        columns['Backstory'] = [c[1] for c in data.schema['Backstory']]
        rows = {}
        for t in ('Backstory', 'Block', 'BlockCondition', 'StoryNode', 'Trait', 'ContactBackstory'):
            data.connection.row_factory = sqlite3.Row
            rows[t] = [dict(r) for r in data.connection.execute('SELECT * FROM ' + quote(t))]
        backstories = {r['BackstoryId']: r for r in rows['Backstory']}
        contacts = {r['ContactBackstoryId']: r for r in rows['ContactBackstory']}
        locale = data.locale
        if not locale:
            raise ValueError('Official/en-US.json is required for character descriptions.')
        entries = {}
        disabled = []
        for block in rows['Block']:
            if not (block['GroupId'] or '').startswith('B_UHUB_Recruit_'):
                continue
            setup = [r for r in rows['BlockCondition'] if r['GroupId'] == block['PostConditionGroup']]
            main = [r for r in setup if r['ConditionType'] == 'AddCharacter'
                    and (r['ActorId'] or '').startswith('PCT_') and r['ConditionValue3'] == 1]
            if not main:
                raise ValueError('Hub entry has no primary recruit: ' + str(block['BlockId']))
            # A secondary NPC in the same setup can also carry RecruitSource=UHUB.
            main = main[0]
            candidates = [r for r in rows['Backstory'] if r['BackstoryGroup'] == main['ConditionValue2']]
            if len(candidates) != 1:
                raise ValueError('Hub backstory group is not singular: ' + str(main['ConditionValue2']))
            bid = candidates[0]['BackstoryId']
            if block['PreConditionGroup'] == 'Pre_AlwaysFail':
                disabled.append(bid)
                continue
            if block['PreConditionGroup']:
                raise ValueError('Review changed Hub precondition: ' + str(block['BlockId']))
            entries[bid] = block, main, setup
        if set(entries) != set(HUB):
            raise ValueError('Available Hub roster changed; review explicit HUB scope: ' + str(sorted(entries)))
        current_starters = {r['BackstoryId'] for r in rows['Backstory'] if r['NewGame'] in (3, 4, 5)}
        if current_starters != set(STARTERS):
            raise ValueError('Combat starter roster changed: ' + str(sorted(current_starters)))

        sql, texts, added, roster = [], {}, {t: [] for t in KEYS}, []
        next_block = BASE

        def add(table, **values):
            nonlocal next_block
            if table == 'Block':
                values['BlockId'] = next_block
                next_block += 1
            cols = columns[table]
            unknown = set(values) - set(cols)
            if unknown:
                raise ValueError(f'{table}: unknown authored fields {unknown}')
            row = {c[1]: (0 if 'INT' in c[2].upper() else '')
                   for c in data.schema[table] if c[1] in cols}
            row.update(values)
            if table == 'Block':
                row['EventType'] = values.get('EventType', 'Event')
            identity = (('BackstoryId',) if table == 'Backstory' else ('BlockId',)
                        if table == 'Block' else ('StoryNodeId',) if table == 'StoryNode'
                        else ('GroupId', 'JsonId'))
            if any(all(r.get(k) == row[k] for k in identity) for r in rows[table]):
                raise ValueError(f'{table}: reserved identity already exists: {row}')
            where = ' AND '.join(f'{quote(k)}={literal(row[k])}' for k in identity)
            sql.append(f'INSERT INTO {quote(table)} ({", ".join(map(quote, cols))}) '
                       f'SELECT {", ".join(literal(row[c]) for c in cols)} '
                       f'WHERE NOT EXISTS (SELECT 1 FROM {quote(table)} WHERE {where});')
            added[table].append(row)
            return row

        def condition(group, kind, **fields):
            seq = 1 + sum(r['GroupId'] == group for r in added['BlockCondition'])
            return add('BlockCondition', GroupId=group, JsonId=seq, ConditionType=kind, **fields)

        def has_character(group, actor, exists):
            condition(group, 'HasCharacter', ActorId=actor, OptionId=1 if exists else -1)

        def copy_condition(source, group, old_actor, new_actor):
            values = {c: source[c] for c in columns['BlockCondition'] if c not in ('GroupId', 'JsonId')}
            for c, v in values.items():
                if isinstance(v, str):
                    values[c] = v.replace(old_actor, new_actor)
            kind = values.pop('ConditionType')
            new = condition(group, kind, **values)
            for suffix in ('Name', 'Desc'):
                for gender in ('', '_Male', '_Female'):
                    old_key = f'BlockCondition.{suffix}.{source["GroupId"]}.{source["JsonId"]}{gender}'
                    if old_key in locale:
                        texts[f'BlockCondition.{suffix}.{group}.{new["JsonId"]}{gender}'] = locale[old_key]

        for index, bid in enumerate(HUB):
            source = backstories[bid]
            block, main, setup = entries[bid]
            clone = dict(source)
            clone_id = BASE + index
            init_group = f'B_{PREFIX}_Start_{bid}'
            post = f'Post_{PREFIX}_Start_{bid}'
            clone.update(BackstoryId=clone_id, BackstoryGroup=1,
                         NewGame=SLOTS[source['JobTypeId']], BlockGroup=init_group)
            add('Backstory', **clone)
            # The starter clone alone runs setup; the original Hub template and
            # its recruitment conversation retain their native records.
            if block['EventId']:
                condition(post, 'StoryMatch', ConditionKey=block['EventId'])
            for operation in setup:
                if operation is not main:
                    copy_condition(operation, post, main['ActorId'], source['CharStoryId'])
            if source['JobTypeId'] in (13, 19):
                condition(post, 'Tag', ActorId=source['CharStoryId'], ConditionKey='ADD_PersonID_StartingHacker')
            add('Block', GroupId=init_group, PostConditionGroup=post if any(
                r['GroupId'] == post for r in added['BlockCondition']) else '',
                PostState1=block['PreState1'].replace('NOT_', 'ADD_', 1))
            traits = [r for r in rows['Trait'] if r['TagMatch'] == source['BackstoryTrait']]
            if len(traits) != 1:
                raise ValueError('Backstory trait must resolve uniquely: ' + str(bid))
            tid = traits[0]['TraitId']
            for gender in ('Male', 'Female'):
                texts[f'Backstory.Title.{clone_id}_{gender}'] = locale.get(
                    f'Backstory.Title.{bid}_{gender}', locale[f'Trait.Name.{tid}_{gender}'])
                texts[f'Backstory.Desc.{clone_id}_{gender}'] = locale.get(
                    f'Backstory.Desc.{bid}_{gender}', locale[f'Trait.Desc.{tid}_{gender}'])
            for suffix in ('CodeName', 'GivenName', 'Surname'):
                key = f'Backstory.{suffix}.{bid}'
                if key in locale:
                    texts[f'Backstory.{suffix}.{clone_id}'] = locale[key]
            roster.append({'direction': 'Hub to start', 'source': bid, 'template': clone_id,
                           'slot': clone['NewGame'], 'name': locale[f'Trait.Name.{tid}_Male']})

        for bid in STARTERS:
            source = backstories[bid]
            key = f'{PREFIX}_{bid}'
            actor = 'PCT_' + key
            node, cooldown_node = 'SN_' + key, 'SN_' + key + '_Cooldown'
            absent, create, hire, fire = ('Pre_' + key + '_Absent', 'Post_' + key + '_Create',
                                         'Post_' + key + '_Hire', 'Post_' + key + '_Fire')
            options, setup_group = 'B_' + key + '_Options', 'B_' + key + '_Setup'
            has_character(absent, 'PTG_' + source['TagID'], False)
            primary = condition(create, 'AddCharacter', ActorId=actor, ConditionValue=bid, ConditionValue3=1)
            name = locale.get(f'Backstory.GivenName.{bid}', '')
            if name:
                texts[f'BlockCondition.Name.{create}.{primary["JsonId"]}'] = name
            condition(hire, 'Recruit', ActorId=actor, ConditionValue=1)
            condition(hire, 'TempStoryId', ActorId=actor, OptionId=-1, ConditionKey=actor)
            condition(fire, 'Purge', ActorId=actor)
            add('Block', GroupId='B_UHUB_Recruit_' + GROUPS[source['JobTypeId']], Weight=20,
                PreState1='NOT_' + key + '_Hired', PreState2='NOT_' + key + '_Cooldown',
                PreConditionGroup=absent, PostConditionGroup=create,
                PostState1='ADD_' + key + '_Cooldown', StoryNode1='ADD_' + node, EventType='Recruit')
            add('StoryNode', StoryNodeId=node, GroupId=node, StoryNodeType='Recruit',
                OnAddedBlock=setup_group, ExpirationBlock='B_' + key + '_Expires', ExpirationTurns=60)
            add('StoryNode', StoryNodeId=cooldown_node, GroupId=node, StoryNodeType='Regular',
                ExpirationBlock='B_' + key + '_Cooldown', ExpirationTurns=360)
            # Reuse the starter's original contacts and relationship setup.
            # Existing contacts are checked before creation; their current state
            # is retained if another story already introduced them.
            for cid in (source['ContactLink1'], source['ContactLink2']):
                if not cid:
                    continue
                contact = contacts[cid]
                pre_contact, post_contact = 'Pre_' + key + f'_Contact_{cid}', 'Post_' + key + f'_Contact_{cid}'
                contact_actor = 'NTG_' + contact['TagID']
                has_character(pre_contact, contact_actor, False)
                condition(post_contact, 'AddCharacter', ActorId=contact['ContactStoryId'], ConditionValue=cid)
                add('Block', GroupId=setup_group, PreConditionGroup=pre_contact, PostConditionGroup=post_contact)
            if source['BlockGroup']:
                if not any(r['GroupId'] == source['BlockGroup'] for r in rows['Block']):
                    raise ValueError('Starter initialization group missing: ' + source['BlockGroup'])
                add('Block', GroupId=setup_group, EventId=source['BlockGroup'], EventType='Group')
            talk = add('Block', GroupId='B_' + key + '_Talk', StoryNodeId=node,
                       ActorId=actor, InterpolateActorId=actor, DialogSide=1, ChoiceMeta=7,
                       EventId=options, EventType='Choice')
            for gender in ('Male', 'Female'):
                texts[f'BlockDesc.{talk["BlockId"]}_{gender}'] = locale[f'Backstory.Desc.{bid}_{gender}']
            yes = add('Block', GroupId=options, ActorId='PCP_Knight', InterpolateActorId=actor,
                      ChoiceMeta=6, PostConditionGroup=hire, PostState1='ADD_' + key + '_Hired',
                      PostState2='DEL_' + key + '_Cooldown', StoryNode1='DEL_' + node,
                      StoryNode2='DEL_' + cooldown_node)
            for gender in ('Male', 'Female'):
                texts[f'BlockDesc.{yes["BlockId"]}_{gender}'] = 'Recruit {1}.'
            later = add('Block', GroupId=options, ActorId='PCP_Knight', ChoiceMeta=2,
                        PreState1='NOT_' + key + '_Expires')
            texts[f'BlockDesc.{later["BlockId"]}'] = 'I need more time to decide.'
            no = add('Block', GroupId=options, ActorId='PCP_Knight', InterpolateActorId=actor,
                     ChoiceMeta=-2, PostConditionGroup=fire, StoryNode1='DEL_' + node,
                     StoryNode2='ADD_' + cooldown_node)
            for gender in ('Male', 'Female'):
                texts[f'BlockDesc.{no["BlockId"]}_{gender}'] = 'Decline {1}.'
            add('Block', GroupId='B_' + key + '_Expires', PostState1='ADD_' + key + '_Expires',
                EventId=options, EventType='Choice')
            add('Block', GroupId='B_' + key + '_Cooldown', PostState1='DEL_' + key + '_Cooldown',
                PostState2='DEL_' + key + '_Expires')
            roster.append({'direction': 'Starter to Hub', 'source': bid,
                           'group': GROUPS[source['JobTypeId']], 'name': name})

        source = {'Metadata': {'Name': 'Hire Everyone', 'StartingId': BASE},
                  'RawSQL': sql, 'RawText': {'Generic': texts}}
        return source, added, {'roster': roster, 'excludedUnfinished': sorted(disabled),
                               'startingSlots': dict(Counter(r['slot'] for r in roster if 'slot' in r))}


def verify(database, sql_bytes, text_bytes, expected, source_text):
    with StaticData(database) as original:
        memory = sqlite3.connect(':memory:')
        original.connection.backup(memory)
        before = {t: memory.execute('SELECT * FROM ' + quote(t)).fetchall() for t in original.schema}
        # Content changes are strictly additive, including the original roster.
        def authorizer(action, table, column, db, trigger):
            if action in (sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE):
                return sqlite3.SQLITE_DENY
            if action == sqlite3.SQLITE_INSERT and table not in KEYS:
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        memory.set_authorizer(authorizer)
        memory.executescript(sql_bytes.decode('utf-8-sig'))
        memory.row_factory = sqlite3.Row
        after = {}
        for table in original.schema:
            baseline = set(before[table])
            current = [tuple(r) for r in memory.execute('SELECT * FROM ' + quote(table))]
            if not baseline <= set(current):
                raise ValueError('Existing native row changed: ' + table)
            new = [r for r in memory.execute('SELECT * FROM ' + quote(table)) if tuple(r) not in baseline]
            want = expected.get(table, [])
            got = [{c: r[c] for c in want[0]} for r in new] if want else []
            if len(new) != len(want) or sorted(got, key=repr) != sorted(want, key=repr):
                raise ValueError('Inserted row mismatch: ' + table)
            after[table] = current
        parsed = json.loads(text_bytes.decode('utf-8-sig'))
        if parsed != source_text:
            raise ValueError('Parser localization differs from reviewed source.')
        memory.executescript(sql_bytes.decode('utf-8-sig'))
        for table in original.schema:
            if [tuple(r) for r in memory.execute('SELECT * FROM ' + quote(table))] != after[table]:
                raise ValueError('Repeat application changed content: ' + table)
        # Check every authored link against native + added content.
        blocks = {r['GroupId'] for r in memory.execute('SELECT * FROM Block')}
        conditions = {r['GroupId'] for r in memory.execute('SELECT * FROM BlockCondition')}
        nodes = {r['StoryNodeId'] for r in memory.execute('SELECT * FROM StoryNode')}
        matches = {r[0] for r in memory.execute('SELECT DISTINCT GroupId FROM StoryMatch')}
        for r in expected['Block']:
            for col in ('PreConditionGroup', 'PostConditionGroup', 'PreDialogPostCondition'):
                if r[col] and r[col] not in conditions:
                    raise ValueError('Missing condition group: ' + r[col])
            if r['EventType'] in ('Group', 'Choice') and r['EventId'] not in blocks:
                raise ValueError('Missing block group: ' + r['EventId'])
            for col in ('StoryNode1', 'StoryNode2', 'StoryNode3'):
                if r[col] and r[col][4:] not in nodes:
                    raise ValueError('Missing story node: ' + r[col])
        for r in expected['StoryNode']:
            for col in ('OnAddedBlock', 'ExpirationBlock'):
                if r[col] and r[col] not in blocks:
                    raise ValueError('Missing node block: ' + r[col])
        for r in expected['BlockCondition']:
            if r['ConditionType'] == 'StoryMatch' and r['ConditionKey'] not in matches:
                raise ValueError('Missing casting group: ' + r['ConditionKey'])
        verify_policy(memory)
        memory.close()
    return {'status': 'PASS', 'nativeRowsUnchanged': True, 'repeatApplication': 'PASS',
            'addedRows': {t: len(rs) for t, rs in expected.items()},
            'localizationKeys': len(parsed), 'gameplay': 'NOT RUN: review before a game session'}


def verify_policy(connection):
    """Check the requested roster and guards independently of generated rows."""
    backstories = {r['BackstoryId']: dict(r) for r in connection.execute('SELECT * FROM Backstory')}
    blocks = [dict(r) for r in connection.execute('SELECT * FROM Block')]
    conditions = [dict(r) for r in connection.execute('SELECT * FROM BlockCondition')]
    for index, source_id in enumerate(HUB):
        native = backstories[source_id]
        clone = backstories[BASE + index]
        wanted_slot = 4 if native['JobTypeId'] in (13, 19) else 3 if native['JobTypeId'] in (12, 5) else 5
        wanted = dict(native, BackstoryId=BASE + index, BackstoryGroup=1,
                      NewGame=wanted_slot, BlockGroup=f'B_{PREFIX}_Start_{source_id}')
        if clone != wanted:
            raise ValueError('Starting template changed character data or uses the wrong slot: ' + str(source_id))
        original_entries = [b for b in blocks if (b['GroupId'] or '').startswith('B_UHUB_Recruit_')
                            and any(c['GroupId'] == b['PostConditionGroup']
                                    and c['ConditionType'] == 'AddCharacter'
                                    and c['ConditionValue2'] == native['BackstoryGroup']
                                    and (c['ActorId'] or '').startswith('PCT_') for c in conditions)]
        if len(original_entries) != 1:
            raise ValueError('Original Hub entry lost: ' + str(source_id))
        flag = original_entries[0]['PreState1'].replace('NOT_', 'ADD_', 1)
        init = [b for b in blocks if b['GroupId'] == clone['BlockGroup']]
        if len(init) != 1 or init[0]['PostState1'] != flag:
            raise ValueError('Starting Hub character lacks its native hired guard: ' + str(source_id))
    actual = []
    for b in blocks:
        if b['BlockId'] < BASE or b['EventType'] != 'Recruit':
            continue
        creation = [c for c in conditions if c['GroupId'] == b['PostConditionGroup']
                    and c['ConditionType'] == 'AddCharacter' and c['ConditionValue3'] == 1]
        if len(creation) != 1:
            raise ValueError('Recruit entry lacks exactly one player character')
        bid = creation[0]['ConditionValue']
        actual.append(bid)
        if bid not in STARTERS:
            raise ValueError('Unexpected Hub starter, Face or Knight: ' + str(bid))
        native = backstories[bid]
        if b['GroupId'] != 'B_UHUB_Recruit_' + GROUPS[native['JobTypeId']]:
            raise ValueError('Starter is in the wrong Hub class: ' + str(bid))
        guards = [c for c in conditions if c['GroupId'] == b['PreConditionGroup']]
        if len(guards) != 1 or guards[0]['ConditionType'] != 'HasCharacter' or guards[0]['OptionId'] != -1 or guards[0]['ActorId'] != 'PTG_' + native['TagID']:
            raise ValueError('Starter lacks the existing-character guard: ' + str(bid))
    if sorted(actual) != sorted(STARTERS):
        raise ValueError('Starter Hub coverage is incomplete or duplicated')


def selftest(database):
    import copy
    source, expected, _summary = build(database)
    sql_bytes = ('\n'.join(source['RawSQL']) + '\n').encode('utf-8')
    text_bytes = encode(source['RawText']['Generic'])
    verify(database, sql_bytes, text_bytes, expected, source['RawText']['Generic'])
    passed = ['additive scope, pointers, slots, duplicate guards, and repeat application']
    for name, operation in [
        ('native UPDATE refused', 'UPDATE Backstory SET NewGame=0 WHERE BackstoryId=22;'),
        ('native DELETE refused', 'DELETE FROM Backstory WHERE BackstoryId=22;'),
        ('unrelated INSERT refused', 'INSERT INTO Rule (RuleId) VALUES (384154000);')]:
        try:
            verify(database, sql_bytes + operation.encode(), text_bytes, expected, source['RawText']['Generic'])
        except (ValueError, sqlite3.DatabaseError):
            passed.append(name)
        else:
            raise AssertionError(name)
    # Change both the SQL result and its expected rows: policy checks must still
    # catch an incorrect slot or a missing duplicate guard.
    for name in ('wrong starting slot refused', 'missing duplicate guard refused'):
        altered = copy.deepcopy(expected)
        if name.startswith('wrong'):
            altered['Backstory'][0]['NewGame'] = 5
        else:
            guard = next(r for r in altered['BlockCondition'] if r['ConditionType'] == 'HasCharacter')
            guard['OptionId'] = 1
        with StaticData(database) as original:
            memory = sqlite3.connect(':memory:')
            original.connection.backup(memory)
            memory.executescript(sql_bytes.decode())
            if name.startswith('wrong'):
                memory.execute('UPDATE Backstory SET NewGame=5 WHERE BackstoryId=?', (BASE,))
            else:
                memory.execute('UPDATE BlockCondition SET OptionId=1 WHERE GroupId=?', (guard['GroupId'],))
            memory.row_factory = sqlite3.Row
            try:
                verify_policy(memory)
            except ValueError:
                passed.append(name)
            else:
                raise AssertionError(name)
            finally:
                memory.close()
    return passed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=DEFAULT_DB)
    parser.add_argument('--out', type=Path, default=PROJECT)
    parser.add_argument('--install', action='store_true')
    parser.add_argument('--selftest', action='store_true')
    args = parser.parse_args()
    if args.selftest:
        print(json.dumps({'status': 'PASS', 'checks': selftest(args.data)}, indent=2))
        return
    schema = MODKIT / 'CyberKnightsModkit_Data/StreamingAssets/config.json'
    watched = [args.data, args.data.parent / 'en-US.json', Path(__file__), schema]
    inputs = {p: state(p) for p in watched}
    destinations = [args.out / 'source_data/stories.manifest', args.out / 'source_data/hire-everyone.json',
                    args.out / 'prepared/_data/data.sql', args.out / 'prepared/_data/en-US.json',
                    args.out / 'review.json']
    if args.install:
        manifest = UPLOADER / 'source_data/stories.manifest'
        inputs[manifest] = state(manifest)
        if manifest.exists() and manifest.read_text(encoding='utf-8-sig').strip() != 'hire-everyone.json':
            raise ValueError('HireEveryone manifest belongs to another source; nothing written.')
        destinations += [UPLOADER / 'source_data/stories.manifest', UPLOADER / 'source_data/hire-everyone.json']
        destinations += [folder / name for folder in (UPLOADER / 'upload_content/_data', WORKSHOP / '_data')
                         for name in ('data.sql', 'en-US.json')]
    expected_states = {p: state(p) for p in destinations}
    source, expected, summary = build(args.data)
    source_bytes = encode(source)
    files, parser_inputs = prepare_parser(source_bytes, UPLOADER, schema, 'hire-everyone.json')
    inputs.update(parser_inputs)
    report = verify(args.data, files['data.sql'], files['en-US.json'], expected, source['RawText']['Generic'])
    report.update(summary)
    report['inputs'] = {str(p): s[2] if s is not None else None for p, s in inputs.items()}
    report['files'] = {n: hashlib.sha256(b).hexdigest() for n, b in files.items()}
    outputs = {args.out / 'source_data/stories.manifest': b'hire-everyone.json\n',
               args.out / 'source_data/hire-everyone.json': source_bytes,
               args.out / 'review.json': encode(report)}
    outputs.update({args.out / 'prepared/_data' / n: b for n, b in files.items()})
    if args.install:
        if not UPLOADER.is_dir() or not WORKSHOP.is_dir():
            raise ValueError('The user-created HireEveryone project and Workshop folder must exist.')
        outputs.update({UPLOADER / 'source_data/stories.manifest': b'hire-everyone.json\n',
                        UPLOADER / 'source_data/hire-everyone.json': source_bytes})
        outputs.update({folder / name: content for folder in (UPLOADER / 'upload_content/_data', WORKSHOP / '_data')
                        for name, content in files.items()})
    written = commit_files(outputs, expected_states, inputs)
    print(json.dumps({'status': 'PASS', 'written': written, 'report': report}, indent=2, ensure_ascii=True))


if __name__ == '__main__':
    main()
