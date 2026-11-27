"""Build the Hire Everyone Workshop data mod from Official content.

Only content SQL is prepared/installed. No game process or campaign is opened.
The installed Modkit parser and an independent in-memory SQL check run first.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
if __name__ == '__main__':
    sys.path.insert(0, str(ROOT / 'gui'))
from static_data import StaticData, DEFAULT_DB, database_path, quote
from modkit import commit_files, payload_paths, state, prepare_parser, steam_workshop
import hire_backstories
import hire_backstory_copy
from hire_backstories import FIRST_ID as BASE, LAST_ID, mod_id

MODKIT = Path(r'C:\Program Files (x86)\Steam\steamapps\common\Cyber Knights Mod Uploader')
UPLOADER = MODKIT / 'WorkshopContent/HireEveryone'
WORKSHOP = MODKIT.parents[1] / 'workshop/content/1021210/3841540859'
CONFIG = MODKIT.parent / 'Cyber Knights Flashpoint/BepInEx/config'
PROJECT = ROOT / 'ckf-hire-everyone'
FILE = 'ckf.hire-everyone.json'
SOURCE = 'hire-everyone.json'
LINKED_SETUP_OFFSET = 192
BACKSTORY_BLOCK_OFFSET = 256
# The original roster's order controls its published IDs. Further starters
# have explicit setup block IDs so existing starter-to-Hub blocks keep theirs.
ORIGINAL_HUB = (4000, 4003, 4004, 4005, 4006, 4008, 4009, 4011, 4012,
                4013, 4014, 4015, 4016, 305000, 305100)
RACER = 305800
HUB = (*ORIGINAL_HUB, RACER)
RACER_SETUP_BLOCK = BASE + LINKED_SETUP_OFFSET - 1
RACER_STEALTH_RELOAD_BLOCK = BASE + 253
STEALTH_CONTACT_RELOAD_BLOCK = BASE + 132
STEALTH_CONTACTS = ((14, 5002), (33, 5014))
STARTERS = (14, 18, 19, 20, 22, 23, 24, 25, 28, 33, 35, 38)
SLOTS = {13: 4, 19: 4, 12: 3, 5: 3, 8: 3, 2: 5, 3: 5, 7: 5, 11: 5, 14: 5, 15: 5}
GROUPS = {13: 'Hackers', 19: 'Wireghosts', 12: 'Vanguards', 5: 'AgentEXs',
          2: 'Warmachines', 3: 'Cyberswords', 7: 'Soldiers', 11: 'Snipers',
          14: 'Gunslingers', 15: 'Scourges'}
KEYS = {'Backstory': 'BackstoryId', 'Block': 'Id',
        'BlockCondition': 'BlockConditionId', 'StoryNode': 'NodeId',
        'Dialog': 'DialogId', 'StoryMatch': 'StoryMatchId', 'Tag': 'JsonId'}
IDENTITIES = {'Backstory': ('BackstoryId',), 'Block': ('BlockId',), 'StoryNode': ('StoryNodeId',),
              'Tag': ('JsonId',), 'StoryMatch': ('StoryMatchId',),
              'Dialog': ('GroupId', 'JsonId'), 'BlockCondition': ('GroupId', 'JsonId')}
AUTHORED_NUMERIC_IDS = {'Backstory': 'BackstoryId', 'Block': 'BlockId', 'StoryMatch': 'StoryMatchId',
                        'Tag': 'JsonId', 'BlockCondition': 'JsonId', 'Dialog': 'JsonId'}
ORIGINS = {
    'Post_Amnesia_TutorialSkipOrEnd': {3: 98, 5: 99},
    'Post_SynDebts_TutorialSkipOrEnd': {3: 3, 5: 2},
}
ORIGIN_CASTING = (
    ('BlockCondition', 'Pre_HasVanguard', 1, 'PCP_Emille', 'PTG_JobMem_Vanguard'),
    ('BlockCondition', 'Pre_HasAgentEX', 1, 'PCP_Soren', 'PTG_JobMem_AgentEX'),
    ('Dialog', 'D_Amnesia_Intro', 7, 'PCP_Emille', 'PTG_JobMem_Stealth'),
)
STARTING_GROUPS = [
    {'slot': 3, 'name': 'Vanguard / Agent EX', 'deploys': True},
    {'slot': 4, 'name': 'Hacker / Wireghost', 'deploys': False},
    {'slot': 5, 'name': 'Other combat classes', 'deploys': True},
]


def encode(value):
    return (json.dumps(value, indent=2, ensure_ascii=False) + '\n').encode('utf-8')


def validate(document):
    if (not isinstance(document, dict) or set(document) != {'format', 'starters', 'hub'}
            or type(document['format']) is not int or document['format'] != 1):
        raise ValueError('Hire Everyone needs a format 1 roster.')
    starters, hub = document['starters'], document['hub']
    if (not isinstance(starters, dict) or set(starters) != {str(i) for i in STARTERS}
            or any(type(value) is not bool for value in starters.values())):
        raise ValueError('Hire Everyone needs one checkbox for each shipped combat starter.')
    if (not isinstance(hub, dict) or set(hub) != {str(i) for i in HUB}
            or any(not isinstance(row, dict) or set(row) != {'include', 'slot'}
                   or type(row['include']) is not bool or type(row['slot']) is not int
                   or row['slot'] not in (3, 4, 5) for row in hub.values())):
        raise ValueError('Hire Everyone needs a checkbox and starting group for each Hub recruit.')
    return document


def load(config_dir):
    path = Path(config_dir) / FILE
    if path.is_file():
        document = json.loads(path.read_text(encoding='utf-8-sig'))
        hub = document.get('hub') if isinstance(document, dict) else None
        if isinstance(hub, dict) and set(hub) == {str(bid) for bid in ORIGINAL_HUB}:
            hub[str(RACER)] = {'include': True, 'slot': SLOTS[8]}
        return validate(document)
    return None


def defaults(backstories):
    return {'format': 1, 'starters': {str(bid): True for bid in STARTERS},
            'hub': {str(bid): {'include': True, 'slot': SLOTS[backstories[bid]['JobTypeId']]}
                    for bid in HUB}}


def official_rows(data, tables):
    data.connection.row_factory = sqlite3.Row
    return {table: [dict(r) for r in data.connection.execute('SELECT * FROM ' + quote(table))]
            for table in tables}


def model(config_dir, database, project):
    result = {'document': None, 'groups': STARTING_GROUPS, 'projectDir': project, 'error': None,
              'titles': {'starters': 'Shipped Starters', 'hub': 'Shipped Underworld Hub'}}
    try:
        result['document'] = load(config_dir)
        if database is False:
            raise ValueError('Select Official data.db under Workshop export to load the shipped rosters.')
        with StaticData(database) as data:
            if not data.locale:
                raise ValueError('Place Official en-US.json beside data.db to show character names.')
            content = official_rows(data, ('Backstory', 'Trait', *hire_backstories.STORY_TABLES))
            rows = {r['BackstoryId']: r for r in content['Backstory']}
            traits = {r['TagMatch']: r['TraitId'] for r in content['Trait']}
            baseline = defaults(rows)
            entries, _unfinished = hire_backstories.hub_entries(content)
            stories = hire_backstories.Stories(content, data.locale)
            for key, ids in (('starters', STARTERS), ('hub', (*HUB, *sorted(set(entries) - set(HUB))))):
                result[key] = []
                for bid in ids:
                    row = rows[bid]
                    title = (data.locale.get(f'Backstory.Title.{bid}_Male')
                             or data.locale.get(f'Trait.Name.{traits.get(row["BackstoryTrait"])}_Male')
                             or row['BackstoryTrait'] or f'Backstory {bid}')
                    item = {'id': bid, 'name': data.locale.get(f'Backstory.GivenName.{bid}', title),
                        'backstory': title, 'job': data.locale.get(f'Job.Name.{row["JobTypeId"]}.Male', f'Class {row["JobTypeId"]}'),
                        'defaultSlot': SLOTS.get(row['JobTypeId'])}
                    if key == 'hub':
                        item['editable'] = bid in HUB
                        try:
                            hire_backstories.check_coverage(stories, row, entries[bid],
                                                            BASE + BACKSTORY_BLOCK_OFFSET, hire_backstories.deadline(0))
                        except (KeyError, ValueError) as exc:
                            item['backstoryIssue'] = str(exc)
                    result[key].append(item)
            result['document'] = result['document'] or baseline
    except (KeyError, OSError, ValueError, sqlite3.Error) as exc:
        result['error'] = str(exc)
    return result


def literal(value):
    if value is None:
        return 'NULL'
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def origin_casting_sql():
    statements = []
    for table, group, sequence, original, replacement in ORIGIN_CASTING:
        guard = ('"ConditionType"=\'HasCharacter\' AND "OptionId"=1' if table == 'BlockCondition'
                 else '"InterpolateActorId"=\'CUR_HACK\'')
        statements.append(f'UPDATE {quote(table)} SET "ActorId"={literal(replacement)} '
                          f'WHERE "GroupId"={literal(group)} AND "JsonId"={sequence} '
                          f'AND "ActorId"={literal(original)} AND {guard};')
    return statements


def emit_stealth_contact_repair(stories, backstories, document, add, condition):
    absent = mod_id('Pre_StealthContactsAbsent')
    contacts = []
    for bid, cid in STEALTH_CONTACTS:
        starter, contact = backstories[bid], stories.contact_ids[cid]
        original_actor, seller = starter['CharStoryId'], contact['ContactStoryId']
        if starter['NewGame'] != 3 or starter['ContactLink1'] != cid or contact['Status'] != 1 or not seller:
            raise ValueError(f'Review the shipped stealth starter and contact pair {bid}/{cid}')
        identity, tag = hire_backstories.contact_identity(contact, seller, stories.tags)
        hire_backstories.contact_presence(condition, absent, identity, tag, False)
        if seller != identity:
            hire_backstories.contact_presence(condition, absent, seller, tag, False)
        relationships = [r for b in stories.blocks[starter['BlockGroup']]
                         for r in stories.conditions[b['PostConditionGroup']]
                         if r['ConditionType'] == 'Tag' and r['ConditionKey'].startswith('ADD_RelTag_')
                         and {r['ActorId'], r['ActorId2']} == {original_actor, seller}]
        if len(relationships) != 2 or {r['ActorId'] for r in relationships} != {original_actor, seller}:
            raise ValueError(f'Review the shipped stealth contact relationship {bid}/{cid}')
        contacts.append((cid, seller, original_actor, relationships))

    entry, starters = mod_id('B_StealthContactEntry'), mod_id('B_StealthContactStarters')
    add('Block', BlockId=STEALTH_CONTACT_RELOAD_BLOCK, GroupId=mod_id('B_Reload_StealthContact'),
        EventType='ReloadGroup', EventId=entry, PreConditionGroup=absent)
    add('Block', BlockId=STEALTH_CONTACT_RELOAD_BLOCK + 1, GroupId=entry,
        EventType='GroupFirst', EventId=starters)
    # A stock merc recruited later has a Hub hired flag. An alternate starter
    # has the initialization flag from its New Game template.
    stock = [(bid, 'NOT_' + mod_id(f'Hub_{bid}_Hired')) for bid, _ in STEALTH_CONTACTS]
    alternates = [(bid, 'HAS_' + mod_id(f'Finish_{bid}_Queued')) for bid in HUB]
    for index, (bid, state) in enumerate(stock + alternates):
        if bid in HUB and document['hub'][str(bid)] != {'include': True, 'slot': 3}:
            continue
        block_id = STEALTH_CONTACT_RELOAD_BLOCK + 2 + 3 * index
        actor = backstories[bid]['CharStoryId']
        roster = mod_id(f'Pre_StealthContactStarter_{bid}')
        choices = mod_id(f'B_StealthContactChoices_{bid}')
        condition(roster, 'HasCharacter', ActorId=actor, OptionId=1)
        add('Block', BlockId=block_id, GroupId=starters, PreState1=state,
            PreConditionGroup=roster, EventType='RandomOne', EventId=choices)
        for offset, (cid, seller, original_actor, relationships) in enumerate(contacts, 1):
            post = mod_id(f'Post_StealthContact_{bid}_{cid}')
            add('Block', BlockId=block_id + offset, GroupId=choices, Weight=1,
                PreConditionGroup=absent, PostConditionGroup=post)
            condition(post, 'AddCharacter', ActorId=seller, ConditionValue=cid)
            for relation in relationships:
                fields = {key: relation[key] for key in ('ActorId', 'ActorId2', 'ConditionKey', 'OptionId')}
                for key in ('ActorId', 'ActorId2'):
                    if fields[key] == original_actor:
                        fields[key] = actor
                condition(post, 'Tag', **fields)


def build(database, document=None):
    with StaticData(database) as data:
        columns = {t: [c[1] for c in data.schema[t] if not c[5]] for t in KEYS}
        for table in ('Backstory', 'StoryMatch', 'Tag'):
            columns[table] = [c[1] for c in data.schema[table]]
        rows = official_rows(data, (*KEYS, 'Trait', 'ContactBackstory'))
        backstories = {r['BackstoryId']: r for r in rows['Backstory']}
        contacts = {r['ContactBackstoryId']: r for r in rows['ContactBackstory']}
        locale = data.locale
        if not locale:
            raise ValueError('Official/en-US.json is required for character descriptions.')
        entries, disabled = hire_backstories.hub_entries(rows)
        missing = set(HUB) - entries.keys()
        if missing:
            raise ValueError('Authored Hub recruits missing from the shipped roster: ' + str(sorted(missing)))
        stories = hire_backstories.Stories(rows, locale)
        current_starters = {r['BackstoryId'] for r in rows['Backstory'] if r['NewGame'] in (3, 4, 5)}
        if current_starters != set(STARTERS):
            raise ValueError('Combat starter roster changed: ' + str(sorted(current_starters)))
        document = defaults(backstories) if document is None else validate(document)

        authored, texts, added, roster = [], {}, {t: [] for t in KEYS}, []
        reserved = {table: {tuple(row[k] for k in fields) for row in rows[table]}
                    for table, fields in IDENTITIES.items()}
        condition_counts = Counter()
        finish_events = []
        next_block = BASE
        next_linked_setup_block = BASE + LINKED_SETUP_OFFSET

        def add(table, **values):
            nonlocal next_block
            if table == 'Block' and 'BlockId' not in values:
                if next_block >= STEALTH_CONTACT_RELOAD_BLOCK:
                    raise ValueError('Starter and Hub blocks exceed their reserved portion of the ID range.')
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
            identity = IDENTITIES[table]
            row_key = tuple(row[k] for k in identity)
            if row_key in reserved[table]:
                raise ValueError(f'{table}: reserved identity already exists: {row}')
            reserved[table].add(row_key)
            where = ' AND '.join(f'{quote(k)}={literal(row[k])}' for k in identity)
            authored.append((table, cols, row, where))
            added[table].append(row)
            return row

        def condition(group, kind, seq=None, **fields):
            condition_counts[group] += 1
            if seq is None:
                seq = BASE + condition_counts[group] - 1
            return add('BlockCondition', GroupId=group, JsonId=seq, ConditionType=kind, **fields)

        def has_character(group, actor, exists):
            condition(group, 'HasCharacter', ActorId=actor, OptionId=1 if exists else -1)

        def linked_setup_block(group, **fields):
            nonlocal next_linked_setup_block
            if next_linked_setup_block >= hire_backstories.RACER_DEBT_SETUP.start:
                raise ValueError('Linked contact setup exceeds its reserved IDs.')
            row = add('Block', GroupId=group, BlockId=next_linked_setup_block, **fields)
            next_linked_setup_block += 1
            return row

        for index, bid in enumerate(HUB):
            source = backstories[bid]
            selection = document['hub'][str(bid)]
            if not selection['include']:
                if bid in ORIGINAL_HUB:
                    next_block += 1  # Keep the published block ID of every other character.
                continue
            slot = selection['slot']
            block, main, setup = entries[bid]
            if block['PreConditionGroup']:
                raise ValueError('Review changed Hub precondition: ' + str(block['BlockId']))
            clone = dict(source)
            clone_id = BASE + index
            init_group = mod_id(f'B_Start_{bid}')
            post = mod_id(f'Post_Start_{bid}')
            clone.update(BackstoryId=clone_id, BackstoryGroup=1,
                         NewGame=slot, BlockGroup=init_group)
            add('Backstory', **clone)
            # The starter clone alone runs setup; the original Hub template and
            # its recruitment conversation retain their native records.
            base = BASE + BACKSTORY_BLOCK_OFFSET + hire_backstories.BLOCKS_PER_BACKSTORY * index
            finish_events.append((bid, source, block, main['ActorId'], setup, base, hire_backstories.deadline(index)))
            casting_tag = ''
            if slot == 4:
                casting_tag = 'PersonID_StartingHacker'
            elif slot == 3 and bid == RACER:
                casting_tag = 'JobMem_Stealth'
            if casting_tag:
                condition(post, 'Tag', ActorId=source['CharStoryId'], ConditionKey='ADD_' + casting_tag)
            queued = mod_id(f'Finish_{bid}_Queued')
            if bid == RACER and slot == 3:
                # The queued flag also exists in campaigns from before the casting tag.
                actor = source['CharStoryId']
                repair = mod_id('Pre_Reload_RacerStealth')
                has_character(repair, actor, True)
                for tag in ('JobMem_Stealth', 'PersonID_StartingHacker'):
                    condition(repair, 'Tag', ActorId=actor, ConditionKey=tag, OptionId=-1)
                add('Block', BlockId=RACER_STEALTH_RELOAD_BLOCK, GroupId=mod_id('B_Reload_RacerStealth'),
                    EventType='ReloadGroup', PreState1='HAS_' + queued,
                    PreConditionGroup=repair, PostConditionGroup=post)
            start_id = {'BlockId': RACER_SETUP_BLOCK} if bid == RACER else {}
            add('Block', GroupId=init_group, PostConditionGroup=post if casting_tag else '',
                EventType='Group', EventId=hire_backstories.setup_id(bid),
                StoryNode1='ADD_' + hire_backstories.node_id(bid),
                PreState1='NOT_' + queued, PostState2='ADD_' + queued,
                PostState1=block['PreState1'].replace('NOT_', 'ADD_', 1), **start_id)
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
                           'slot': slot, 'name': locale[f'Trait.Name.{tid}_Male'],
                           'starterBackstoryEvent': hire_backstories.node_id(bid),
                           'deadlineTurns': hire_backstories.deadline(index),
                           'openingDeployment': {group: starts[slot] for group, starts in ORIGINS.items() if slot in starts}})

        for bid in STARTERS:
            source = backstories[bid]
            if not document['starters'][str(bid)]:
                next_block += 7 + bool(source['BlockGroup']) + sum(bool(source[key]) for key in ('ContactLink1', 'ContactLink2'))
                continue
            key = f'Hub_{bid}'
            actor = mod_id('PCT_' + key)
            node, cooldown_node = mod_id('SN_' + key), mod_id('SN_' + key + '_Cooldown')
            absent, create, hire, fire = (mod_id(name) for name in
                                         (f'Pre_{key}_Absent', f'Post_{key}_Create',
                                          f'Post_{key}_Hire', f'Post_{key}_Fire'))
            options, setup_group = mod_id(f'B_{key}_Options'), mod_id(f'B_{key}_Setup')
            hired, cooldown, expired = (mod_id(f'{key}_{state}') for state in ('Hired', 'Cooldown', 'Expires'))
            expiry_block, cooldown_block = mod_id(f'B_{key}_Expires'), mod_id(f'B_{key}_Cooldown')
            has_character(absent, 'PTG_' + source['TagID'], False)
            primary = condition(create, 'AddCharacter', ActorId=actor, ConditionValue=bid, ConditionValue3=1)
            name = locale.get(f'Backstory.GivenName.{bid}', '')
            if name:
                texts[f'BlockCondition.Name.{create}.{primary["JsonId"]}'] = name
            condition(hire, 'Recruit', ActorId=actor, ConditionValue=1)
            condition(hire, 'TempStoryId', ActorId=actor, OptionId=-1, ConditionKey=actor)
            condition(fire, 'Purge', ActorId=actor)
            add('Block', GroupId='B_UHUB_Recruit_' + GROUPS[source['JobTypeId']], Weight=20,
                PreState1='NOT_' + hired, PreState2='NOT_' + cooldown,
                PreConditionGroup=absent, PostConditionGroup=create,
                PostState1='ADD_' + cooldown, StoryNode1='ADD_' + node, EventType='Recruit')
            add('StoryNode', StoryNodeId=node, GroupId=node, StoryNodeType='Recruit',
                OnAddedBlock=setup_group, ExpirationBlock=expiry_block, ExpirationTurns=60)
            add('StoryNode', StoryNodeId=cooldown_node, GroupId=node, StoryNodeType='Regular',
                ExpirationBlock=cooldown_block, ExpirationTurns=360)
            # Reuse the starter's original contacts and relationship setup.
            # Existing contacts are checked before creation; their current state
            # is retained if another story already introduced them.
            for cid in (source['ContactLink1'], source['ContactLink2']):
                if not cid:
                    continue
                contact = contacts[cid]
                pre_contact, post_contact = mod_id(f'Pre_{key}_Contact_{cid}'), mod_id(f'Post_{key}_Contact_{cid}')
                contact_actor = hire_backstories.permanent_contact_actor(contact, key)
                identity, tag = hire_backstories.contact_identity(contact, contact_actor, stories.tags)
                hire_backstories.contact_presence(condition, pre_contact, identity, tag, False)
                condition(post_contact, 'AddCharacter', ActorId=contact_actor, ConditionValue=cid)
                add('Block', GroupId=setup_group, PreConditionGroup=pre_contact, PostConditionGroup=post_contact)
            if source['BlockGroup']:
                native_setup = stories.blocks[source['BlockGroup']]
                if not native_setup:
                    raise ValueError('Starter initialization group missing: ' + source['BlockGroup'])
                target = source['BlockGroup']
                creators = [(b, c) for b in native_setup for field in ('PreDialogPostCondition', 'PostConditionGroup')
                            for c in stories.conditions[b[field]] if c['ConditionType'] == 'AddCharacter']
                if creators:
                    # Molly's native setup also creates Brandt outside ContactLink1/2.
                    if [(b['BlockId'], c['BlockConditionId']) for b, c in creators] != [(86, 557)]:
                        raise ValueError('Review contact creation in shipped setup for Backstory ' + str(bid))
                    native, action = creators[0]
                    if (len(native_setup) != 1 or native['EventType'] != 'Event' or native['PreConditionGroup']
                            or native['PreState1'] or native['PreState2'] or native['PreDialogPostCondition']
                            or native['Dialog']):
                        raise ValueError('Review Brandt setup before adapting it for a Hub offer')
                    contact = stories.contact(action)
                    actor_id = hire_backstories.permanent_contact_actor(contact, key)
                    identity, tag = hire_backstories.contact_identity(contact, actor_id, stories.tags)
                    guard = mod_id(f'Pre_{key}_LinkedSetup')
                    create_contact = mod_id(f'Post_{key}_LinkedContact')
                    effects = mod_id(f'Post_{key}_LinkedEffects')
                    target = mod_id(f'B_{key}_LinkedSetup')
                    hire_backstories.contact_presence(condition, guard, identity, tag, False)
                    condition(create_contact, 'AddCharacter', ActorId=actor_id, ConditionValue=contact['ContactBackstoryId'])
                    linked_setup_block(target, PreConditionGroup=guard, PostConditionGroup=create_contact)
                    for row in stories.conditions[native['PostConditionGroup']]:
                        if row != action:
                            values = {k: v for k, v in row.items() if k not in
                                      ('BlockConditionId', 'GroupId', 'JsonId', 'ConditionType')}
                            condition(effects, row['ConditionType'], **values)
                    values = {k: native[k] for k in columns['Block'] if k not in ('BlockId', 'GroupId')}
                    values['PostConditionGroup'] = effects
                    linked_setup_block(target, **values)
                add('Block', GroupId=setup_group, EventId=target, EventType='Group')
            talk = add('Block', GroupId=mod_id(f'B_{key}_Talk'), StoryNodeId=node,
                       ActorId=actor, InterpolateActorId=actor, DialogSide=1, ChoiceMeta=7,
                       EventId=options, EventType='Choice')
            for gender in ('Male', 'Female'):
                texts[f'BlockDesc.{talk["BlockId"]}_{gender}'] = locale[f'Backstory.Desc.{bid}_{gender}']
            yes = add('Block', GroupId=options, ActorId='PCP_Knight', InterpolateActorId=actor,
                      ChoiceMeta=6, PostConditionGroup=hire, PostState1='ADD_' + hired,
                      PostState2='DEL_' + cooldown, StoryNode1='DEL_' + node,
                      StoryNode2='DEL_' + cooldown_node)
            for gender in ('Male', 'Female'):
                texts[f'BlockDesc.{yes["BlockId"]}_{gender}'] = 'Recruit {1}.'
            later = add('Block', GroupId=options, ActorId='PCP_Knight', ChoiceMeta=2,
                        PreState1='NOT_' + expired)
            texts[f'BlockDesc.{later["BlockId"]}'] = 'I need more time to decide.'
            no = add('Block', GroupId=options, ActorId='PCP_Knight', InterpolateActorId=actor,
                     ChoiceMeta=-2, PostConditionGroup=fire, StoryNode1='DEL_' + node,
                     StoryNode2='ADD_' + cooldown_node)
            for gender in ('Male', 'Female'):
                texts[f'BlockDesc.{no["BlockId"]}_{gender}'] = 'Decline {1}.'
            add('Block', GroupId=expiry_block, PostState1='ADD_' + expired,
                EventId=options, EventType='Choice')
            add('Block', GroupId=cooldown_block, PostState1='DEL_' + cooldown,
                PostState2='DEL_' + expired)
            roster.append({'direction': 'Starter to Hub', 'source': bid,
                           'group': GROUPS[source['JobTypeId']], 'name': name})

        for index, bid in enumerate(HUB):
            selection = document['hub'][str(bid)]
            if not selection['include']:
                continue
            slot = selection['slot']
            actor = backstories[bid]['CharStoryId']
            for group, starts in ORIGINS.items():
                if slot in starts:
                    seq = BASE + 2 * index
                    condition(group, 'CharAltStart', seq, ActorId=actor, ConditionValue=starts[slot])
                    condition(group, 'CharacterStatus', seq + 1, ActorId=actor, ConditionValue=1, ConditionValue2=1)

        for bid, source, offer, temporary, setup, base, turns in finish_events:
            hire_backstories.emit(stories, bid, source, offer, temporary, setup,
                                  base, turns, add, condition, texts)
        emit_stealth_contact_repair(stories, backstories, document, add, condition)

        sql = [f'INSERT INTO {quote(table)} ({", ".join(map(quote, cols))}) '
               f'SELECT {", ".join(literal(row[c]) for c in cols)} '
               f'WHERE NOT EXISTS (SELECT 1 FROM {quote(table)} WHERE {where});'
               for table, cols, row, where in authored]
        sql.extend(origin_casting_sql())
        source = {'Metadata': {'Name': 'Hire Everyone', 'StartingId': BASE},
                  'RawSQL': sql, 'RawText': {'Generic': texts}}
        return source, added, {'roster': roster, 'excludedUnfinished': sorted(disabled),
                               'outsideStartingScope': sorted(entries.keys() - set(HUB)),
                               'startingSlots': dict(Counter(r['slot'] for r in roster if 'slot' in r))}


def verify_namespace(rows):
    native_groups = {'Block': {'B_UHUB_Recruit_' + group for group in GROUPS.values()},
                     'BlockCondition': ORIGINS}
    local_fields = {'Backstory': ('BlockGroup',), 'Block': ('StoryNodeId', 'PreConditionGroup',
                   'PreDialogPostCondition', 'PostConditionGroup', 'StoryNode1', 'StoryNode2', 'StoryNode3', 'Dialog'),
                    'StoryNode': ('StoryNodeId', 'OnAddedBlock', 'ExpirationStoryNode', 'ExpirationBlock'),
                    'Tag': ('TagId',)}
    for table, added in rows.items():
        id_field = AUTHORED_NUMERIC_IDS.get(table)
        for row in added:
            if id_field and not BASE <= row[id_field] <= LAST_ID:
                raise ValueError(f'{table}.{id_field} is outside the Hire Everyone ID range: {row[id_field]}')
            group = row.get('GroupId')
            if group and group not in native_groups.get(table, ()) and not group.endswith('_HireEveryone'):
                raise ValueError(f'{table}.GroupId lacks the HireEveryone suffix: {group}')
            for col in local_fields.get(table, ()):
                if row[col] and not row[col].endswith('_HireEveryone'):
                    raise ValueError(f'{table}.{col} lacks the HireEveryone suffix: {row[col]}')


def verify(database, sql_bytes, text_bytes, expected, source_text, document=None):
    verify_namespace(expected)
    casting = origin_casting_sql()
    additions, *updates = sql_bytes.decode('utf-8-sig').rstrip('\r\n').rsplit('\n', len(casting))
    if [line.removesuffix('\r') for line in updates] != casting:
        raise ValueError('Packaged origin casting updates differ from the reviewed statements')
    with StaticData(database) as original, closing(sqlite3.connect(':memory:')) as memory:
        original.connection.backup(memory)
        memory.execute('SAVEPOINT expected_casting')
        for statement, (table, group, sequence, _, _) in zip(casting, ORIGIN_CASTING):
            if memory.execute(statement).rowcount != 1:
                raise ValueError(f'Review shipped casting row {table} {group}/{sequence}')
        before = {t: memory.execute('SELECT * FROM ' + quote(t)).fetchall() for t in original.schema}
        memory.execute('ROLLBACK TO expected_casting')
        memory.execute('RELEASE expected_casting')

        def authorizer(action, table, column, db, trigger):
            if action in (sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE):
                return sqlite3.SQLITE_DENY
            if action == sqlite3.SQLITE_INSERT and table not in KEYS:
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        def apply():
            memory.set_authorizer(authorizer)
            try:
                memory.executescript(additions)
            finally:
                memory.set_authorizer(None)
            memory.executescript('\n'.join(updates))

        apply()
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
        apply()
        for table in original.schema:
            if [tuple(r) for r in memory.execute('SELECT * FROM ' + quote(table))] != after[table]:
                raise ValueError('Repeat application changed content: ' + table)
        # Check every authored link against native + added content.
        blocks = {r['GroupId'] for r in memory.execute('SELECT * FROM Block')}
        conditions = {r['GroupId'] for r in memory.execute('SELECT * FROM BlockCondition')}
        nodes = {r['StoryNodeId'] for r in memory.execute('SELECT * FROM StoryNode')}
        matches = {r[0] for r in memory.execute('SELECT DISTINCT GroupId FROM StoryMatch')}
        dialogs = {r[0] for r in memory.execute('SELECT DISTINCT GroupId FROM Dialog')}
        for r in expected['Block']:
            for col in ('PreConditionGroup', 'PostConditionGroup', 'PreDialogPostCondition'):
                if r[col] and r[col] not in conditions:
                    raise ValueError('Missing condition group: ' + r[col])
            routes = r['EventType'] in ('Group', 'GroupFirst', 'TalkOn', 'Choice', 'RandomOne')
            if (routes or (r['EventType'] == 'ReloadGroup' and r['EventId'])) and r['EventId'] not in blocks:
                raise ValueError('Missing block group: ' + r['EventId'])
            if r['Dialog'] and r['Dialog'] not in dialogs:
                raise ValueError('Missing dialogue group: ' + r['Dialog'])
            for col in ('StoryNode1', 'StoryNode2', 'StoryNode3'):
                if r[col] and r[col][4:] not in nodes:
                    raise ValueError('Missing story node: ' + r[col])
        for r in expected['StoryNode']:
            for col in ('OnAddedBlock', 'ExpirationBlock'):
                if r[col] and r[col] not in blocks:
                    raise ValueError('Missing node block: ' + r[col])
            if r['ExpirationStoryNode'] and r['ExpirationStoryNode'] not in nodes:
                raise ValueError('Missing successor node: ' + r['ExpirationStoryNode'])
        for r in expected['BlockCondition']:
            if r['ConditionType'] == 'StoryMatch' and r['ConditionKey'] not in matches:
                raise ValueError('Missing casting group: ' + r['ConditionKey'])
        verify_policy(memory, document, parsed)
    return {'status': 'PASS', 'otherNativeRowsUnchanged': True, 'originCastingUpdates': len(casting),
            'repeatApplication': 'PASS',
            'addedRows': {t: len(rs) for t, rs in expected.items()},
            'localizationKeys': len(parsed), 'gameplay': 'NOT RUN: review before a game session'}


def verify_policy(connection, document=None, locale=None):
    """Check the requested roster and guards independently of generated rows."""
    backstories = {r['BackstoryId']: dict(r) for r in connection.execute('SELECT * FROM Backstory')}
    blocks = [dict(r) for r in connection.execute('SELECT * FROM Block')]
    conditions = [dict(r) for r in connection.execute('SELECT * FROM BlockCondition')]
    verify_contact_guards(connection, blocks, conditions)
    hire_backstories.verify_events(connection, HUB, document or defaults(backstories), locale)
    document = defaults(backstories) if document is None else validate(document)
    roster_actors = {backstories[bid]['CharStoryId'] for bid in HUB + STARTERS}
    for group, starts in ORIGINS.items():
        origin = 'OriginStory_' + group.split('_')[1]
        if not any(b['GroupId'] == origin and b['PostConditionGroup'] == group for b in blocks):
            raise ValueError('Shipped origin no longer calls its deployment group: ' + origin)
        actors = {backstories[bid]['CharStoryId']: starts[backstories[bid]['NewGame']]
                  for bid in STARTERS if backstories[bid]['NewGame'] in starts}
        for bid in HUB:
            entry = document['hub'][str(bid)]
            if entry['include'] and entry['slot'] in starts:
                actors[backstories[bid]['CharStoryId']] = starts[entry['slot']]
        actual = Counter((r['ActorId'], r['ConditionType'], r['ConditionValue'], r['ConditionValue2'])
                         for r in conditions if r['GroupId'] == group and r['ActorId'] in roster_actors)
        wanted = Counter(row for actor, start in actors.items()
                         for row in ((actor, 'CharAltStart', start, 0), (actor, 'CharacterStatus', 1, 1)))
        if actual != wanted:
            raise ValueError('Origin deployment does not match the shipped and selected groups: ' + group)
    for index, source_id in enumerate(HUB):
        native = backstories[source_id]
        clone = backstories.get(BASE + index)
        selection = document['hub'][str(source_id)]
        if not selection['include']:
            if clone is not None:
                raise ValueError('Excluded Hub character has a starting template: ' + str(source_id))
            continue
        wanted_slot = selection['slot']
        wanted = dict(native, BackstoryId=BASE + index, BackstoryGroup=1,
                      NewGame=wanted_slot, BlockGroup=mod_id(f'B_Start_{source_id}'))
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
        wanted_tags = []
        if wanted_slot == 4:
            wanted_tags.append((native['CharStoryId'], 'ADD_PersonID_StartingHacker'))
        if wanted_slot == 3 and source_id == RACER:
            wanted_tags.append((native['CharStoryId'], 'ADD_JobMem_Stealth'))
        actual_tags = [(r['ActorId'], r['ConditionKey']) for r in conditions
                       if r['GroupId'] == init[0]['PostConditionGroup'] and r['ConditionType'] == 'Tag']
        if actual_tags != wanted_tags:
            raise ValueError('Starting casting tags do not match selected group: ' + str(source_id))
    racer = document['hub'][str(RACER)]
    reloads = {b['BlockId']: b for b in blocks
               if BASE <= b['BlockId'] <= LAST_ID and b['EventType'] == 'ReloadGroup'}
    if reloads.pop(STEALTH_CONTACT_RELOAD_BLOCK, None) is None:
        raise ValueError('Missing stealth contact reload')
    wanted_reloads = {RACER_STEALTH_RELOAD_BLOCK} if racer['include'] and racer['slot'] == 3 else set()
    if reloads.keys() != wanted_reloads:
        raise ValueError('Racer stealth reload does not match the selected roster')
    for repair in reloads.values():
        actor = backstories[RACER]['CharStoryId']
        checks = [(r['ConditionType'], r['ActorId'], r['ConditionKey'], r['OptionId'])
                  for r in conditions if r['GroupId'] == repair['PreConditionGroup']]
        actions = [(r['ConditionType'], r['ActorId'], r['ConditionKey'], r['OptionId'])
                   for r in conditions if r['GroupId'] == repair['PostConditionGroup']]
        if (repair['PreState1'] != 'HAS_' + mod_id(f'Finish_{RACER}_Queued')
                or checks != [('HasCharacter', actor, '', 1), ('Tag', actor, 'JobMem_Stealth', -1),
                              ('Tag', actor, 'PersonID_StartingHacker', -1)]
                or actions != [('Tag', actor, 'ADD_JobMem_Stealth', 0)]):
            raise ValueError('Racer stealth reload must only repair a starting Racer missing the stealth tag')
    actual = []
    for b in blocks:
        if not BASE <= b['BlockId'] <= LAST_ID or b['EventType'] != 'Recruit':
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
    if sorted(actual) != sorted(bid for bid in STARTERS if document['starters'][str(bid)]):
        raise ValueError('Starter Hub coverage is incomplete or duplicated')


def verify_contact_guards(connection, blocks, conditions):
    actions = hire_backstories.groups(conditions)
    contacts = [dict(r) for r in connection.execute('SELECT * FROM ContactBackstory')]
    by_id = hire_backstories.groups(contacts, 'ContactBackstoryId')
    by_pool = hire_backstories.groups(contacts, 'BackstoryGroup')
    tags = {r[0] for r in connection.execute('SELECT TagId FROM Tag')}
    for row in conditions:
        if (row['GroupId'].endswith('_HireEveryone') and row['ConditionType'] == 'HasCharacter'
                and row['ActorId'].startswith(('NCP_', 'NCT_', 'NTG_'))):
            raise ValueError(f'Contact {row["ActorId"]} still uses the mercenary lookup')
    for block in blocks:
        if not block['GroupId'].endswith('_HireEveryone'):
            continue
        for field in ('PreDialogPostCondition', 'PostConditionGroup'):
            for row in actions[block[field]]:
                if row['ConditionType'] != 'AddCharacter' or row['ActorId'].startswith('PCT_'):
                    continue
                if not row['ActorId'].startswith(('NCP_', 'NCT_')):
                    raise ValueError(f'Invalid contact actor for {block["BlockId"]}: {row["ActorId"]}')
                candidates = (by_pool[row['ConditionValue2']] if row['ConditionValue'] == -1
                              else by_id[row['ConditionValue']])
                if len(candidates) != 1:
                    raise ValueError(f'Contact creation in {block["BlockId"]} needs one reviewed backstory')
                identity, tag = hire_backstories.contact_identity(candidates[0], row['ActorId'], tags)
                if not any(r['ConditionType'] == 'Tag' and r['OptionId'] == -1
                           and r['ActorId'] == identity and r['ConditionKey'] == tag
                           for r in actions[block['PreConditionGroup']]):
                    raise ValueError(f'Unguarded contact creation in {block["BlockId"]}: {identity}')


def validate_roster(database, document):
    source, expected, _summary = build(database, document)
    texts = source['RawText']['Generic']
    verify(database, '\n'.join(source['RawSQL']).encode('utf-8'), encode(texts), expected, texts, document)


def prepare(database, document, project, contract, inputs):
    source, expected, summary = build(database, document)
    source_bytes = encode(source)
    files, parser_inputs = prepare_parser(source_bytes, project, contract, SOURCE)
    for path, checked in parser_inputs.items():
        if path in inputs and inputs[path] != checked:
            raise ValueError('Parser input changed during preparation: ' + str(path))
        inputs[path] = checked
    report = verify(database, files['data.sql'], files['en-US.json'], expected, source['RawText']['Generic'], document)
    report.update(summary)
    report['files'] = {n: hashlib.sha256(b).hexdigest() for n, b in files.items()}
    return source_bytes, files, report


def project_outputs(project, workshop):
    manifest = project / 'source_data/stories.manifest'
    source = manifest.parent / SOURCE
    payloads = payload_paths(project, workshop)
    expected = {p: state(p) for p in (manifest, source, *payloads)}
    if expected[manifest] is not None:
        entries = [s.strip() for s in manifest.read_text(encoding='utf-8-sig').splitlines()
                   if s.strip() and not s.lstrip().startswith('#')]
        if entries != [SOURCE]:
            raise ValueError('The selected project contains another mod manifest; choose Hire Everyone.')
    return manifest, source, payloads, expected


def send(config_dir, project_dir, database=None, expect=None):
    if not str(project_dir).strip():
        raise ValueError('Choose the initialized Hire Everyone Modkit folder.')
    project, config = Path(project_dir).resolve(), Path(config_dir).resolve()
    if project == config or config in project.parents or not (project / 'upload_content').is_dir():
        raise ValueError('Choose the initialized Hire Everyone Modkit folder outside the live config directory.')
    workshop, inputs = steam_workshop.local_install_target(project, state)
    database = database_path(database)
    tuning = config / FILE
    contract = project.parent / 'config.json'
    inputs.update({p: state(p) for p in (database, database.parent / 'en-US.json', tuning, contract)})
    if expect is not None:
        for key, path in ((FILE, tuning), ('@official-data.db', database)):
            if expect.get(key) != (inputs[path][2] if inputs[path] else None):
                raise ValueError('Hire Everyone inputs changed on disk; reload before sending.')
    manifest, source, payloads, expected = project_outputs(project, workshop)
    source_bytes, files, report = prepare(database, load(config), project, contract, inputs)
    outputs = {manifest: (SOURCE + '\n').encode(), source: source_bytes}
    outputs.update({p: files[p.name] for p in payloads})
    written = commit_files(outputs, expected, inputs)
    return {'ok': True, 'written': written, 'installedDir': str(workshop), 'files': report['files'],
            'next': 'Hire Everyone prepared and installed locally. Start or restart Cyber Knights to test.'}


def selftest(database):
    import copy
    source, expected, _summary = build(database)
    sql_bytes = ('\n'.join(source['RawSQL']) + '\n').encode('utf-8')
    text_bytes = encode(source['RawText']['Generic'])
    verify(database, sql_bytes, text_bytes, expected, source['RawText']['Generic'])
    passed = ['origin casting, additive scope, pointers, slots, duplicate guards, and repeat application']
    for name, operation in [
        ('native UPDATE refused', 'UPDATE Backstory SET NewGame=0 WHERE BackstoryId=22;'),
        ('unreviewed dialogue UPDATE refused', 'UPDATE Dialog SET ActorId=\'PCP_Face\' WHERE DialogId=3380;'),
        ('native DELETE refused', 'DELETE FROM Backstory WHERE BackstoryId=22;'),
        ('unrelated INSERT refused', 'INSERT INTO Rule (RuleId) VALUES (567000);')]:
        try:
            verify(database, operation.encode() + b'\n' + sql_bytes, text_bytes, expected, source['RawText']['Generic'])
        except (ValueError, sqlite3.DatabaseError):
            passed.append(name)
        else:
            raise AssertionError(name)
    # Change both the SQL result and its expected rows: policy checks must still
    # catch an incorrect slot or a missing duplicate guard.
    for name in ('wrong starting slot refused', 'missing duplicate guard refused', 'mercenary lookup for contact refused'):
        altered = copy.deepcopy(expected)
        if name.startswith('wrong'):
            altered['Backstory'][0]['NewGame'] = 5
        elif name.startswith('mercenary'):
            guard = next(r for r in altered['BlockCondition'] if r['ActorId'] == 'NTG_PersonID_Recruit_Agent_Escaped_Son'
                         and r['ConditionType'] == 'Tag' and r['OptionId'] == -1)
        else:
            guard = next(r for r in altered['BlockCondition'] if r['GroupId'] == mod_id(f'Pre_Hub_{STARTERS[0]}_Absent'))
            guard['OptionId'] = 1
        with StaticData(database) as original:
            memory = sqlite3.connect(':memory:')
            original.connection.backup(memory)
            memory.executescript(sql_bytes.decode())
            if name.startswith('wrong'):
                memory.execute('UPDATE Backstory SET NewGame=5 WHERE BackstoryId=?', (BASE,))
            elif name.startswith('mercenary'):
                memory.execute("UPDATE BlockCondition SET ConditionType='HasCharacter' WHERE GroupId=?", (guard['GroupId'],))
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
    with StaticData(database) as original:
        original.connection.row_factory = sqlite3.Row
        selection = defaults({r['BackstoryId']: r for r in original.connection.execute('SELECT * FROM Backstory')})
    selection['hub']['4000']['slot'] = 3
    # Start with the moved-in stealth candidate, then remove other coverage.
    # Adding a slot-3 candidate legitimately introduces its reserved blocks.
    _, covered_rows, _summary = build(database, selection)
    selection['starters']['14'] = False
    selection['hub']['4003']['slot'] = 5
    selection['hub']['4004']['slot'] = 4
    selection['hub']['4005']['include'] = False
    selection['hub'][str(RACER)]['slot'] = 5
    alternate, rows, _summary = build(database, selection)
    texts = alternate['RawText']['Generic']
    verify(database, '\n'.join(alternate['RawSQL']).encode(), encode(texts), rows, texts, selection)
    original_block_ids = {r['BlockId']: r['GroupId'] for r in covered_rows['Block']}
    if any(original_block_ids.get(r['BlockId']) != r['GroupId'] for r in rows['Block']):
        raise AssertionError('Roster exclusions renumbered previously exported blocks')
    passed.append('group changes and exclusions in both origins, starter filtering and stable IDs')
    with StaticData(database) as original:
        with sqlite3.connect(':memory:') as memory:
            original.connection.backup(memory)
            memory.executescript('\n'.join(alternate['RawSQL']))
            memory.execute("DELETE FROM BlockCondition WHERE GroupId='Post_Amnesia_TutorialSkipOrEnd' "
                           "AND ActorId='PCP_UHUB_Hacker' AND ConditionType='CharAltStart'")
            memory.row_factory = sqlite3.Row
            try:
                verify_policy(memory, selection)
            except ValueError as exc:
                if 'Origin deployment' not in str(exc):
                    raise
                passed.append('missing origin deployment row refused')
            else:
                raise AssertionError('Missing origin deployment row passed')
    return passed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=DEFAULT_DB)
    parser.add_argument('--out', type=Path, default=PROJECT)
    parser.add_argument('--config', type=Path, default=CONFIG)
    parser.add_argument('--install', action='store_true')
    parser.add_argument('--selftest', action='store_true')
    args = parser.parse_args()
    if args.selftest:
        print(json.dumps({'status': 'PASS', 'checks': selftest(args.data)}, indent=2))
        return
    schema = MODKIT / 'CyberKnightsModkit_Data/StreamingAssets/config.json'
    watched = [args.data, args.data.parent / 'en-US.json', Path(__file__), Path(hire_backstories.__file__),
               Path(hire_backstory_copy.__file__), schema, args.config / FILE]
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
    source_bytes, files, report = prepare(args.data, load(args.config), UPLOADER, schema, inputs)
    report['inputs'] = {str(p): s[2] if s is not None else None for p, s in inputs.items()}
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
