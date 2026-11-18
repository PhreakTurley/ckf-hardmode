"""Starter-only adaptations of the reviewed Underworld Hub conversations."""
from collections import defaultdict
import re


# BackstoryId -> (trait prompt, follow-up prompt). These anchors are reviewed
# individually. A different conversation needs review before it can ship.
CONVERSATIONS = {
    4000: (91011, 91016), 4003: (91071, 91076), 4004: (91091, 91096),
    4005: (91111, 91116), 4006: (91131, 91136), 4008: (91192, 91197),
    4009: (91212, 91217), 4011: (91231, 91236), 4012: (91251, 91256),
    4013: (91270, 91275), 4014: (91290, 91295), 4015: (91313, 91318),
    4016: (91335, 91340), 305000: (305006, 305011), 305100: (305106, 305111),
}
STORY_TABLES = ('Block', 'BlockCondition', 'Dialog', 'StoryMatch', 'ContactBackstory')
OPERATIONS = {'AddCharacter', 'StoryMatch', 'Tag', 'Trait', 'Obligation', 'Item', 'CharacterStatus', 'PayRate'}


def node_id(prefix, bid):
    return f'SN_{prefix}_Finish_{bid}'


def setup_id(prefix, bid):
    return f'B_{prefix}_Finish_{bid}_Setup'


def groups(rows, field='GroupId'):
    indexed = defaultdict(list)
    for row in rows:
        indexed[row[field]].append(row)
    return indexed


def check_coverage(stories, backstory, entry, prefix, base):
    """Compile the event's rows in memory to report per-character authoring issues."""
    offer, main, setup = entry
    if offer['PreConditionGroup']:
        raise ValueError(f'Hub offer {offer["BlockId"]} has an unreviewed precondition')
    counts = defaultdict(int)

    def condition(group, kind, **fields):
        counts[group] += 1
        return dict(fields, GroupId=group, ConditionType=kind, JsonId=counts[group])

    emit(stories, backstory['BackstoryId'], backstory, offer, main['ActorId'], setup, prefix, base,
         lambda _table, **fields: fields, condition, {})


def hub_entries(rows):
    """Read the shipped Hub offer and its lead actor for every backstory."""
    setups = groups(rows['BlockCondition'])
    pools = groups(rows['Backstory'], 'BackstoryGroup')
    available, unfinished = {}, []
    for block in rows['Block']:
        if not (block['GroupId'] or '').startswith('B_UHUB_Recruit_'):
            continue
        setup = sorted(setups[block['PostConditionGroup']], key=lambda r: r['JsonId'])
        main = next((r for r in setup if r['ConditionType'] == 'AddCharacter'
                     and (r['ActorId'] or '').startswith('PCT_') and r['ConditionValue3'] == 1), None)
        if main is None:
            raise ValueError('Hub entry has no primary recruit: ' + str(block['BlockId']))
        candidates = pools[main['ConditionValue2']]
        if len(candidates) != 1:
            raise ValueError('Hub backstory group is not singular: ' + str(main['ConditionValue2']))
        bid = candidates[0]['BackstoryId']
        if block['PreConditionGroup'] == 'Pre_AlwaysFail':
            unfinished.append(bid)
        elif bid in available:
            raise ValueError('Multiple shipped Hub offers for Backstory ' + str(bid))
        else:
            available[bid] = block, main, setup
    return available, unfinished


class Stories:
    def __init__(self, rows, locale):
        self.locale = locale
        self.blocks = groups(rows['Block'])
        self.by_id = {r['BlockId']: r for r in rows['Block']}
        self.by_node = groups(rows['Block'], 'StoryNodeId')
        self.conditions = groups(rows['BlockCondition'])
        self.dialogs = groups(rows['Dialog'])
        self.matches = groups(rows['StoryMatch'])
        self.contacts = groups(rows['ContactBackstory'], 'BackstoryGroup')
        self.contact_ids = {r['ContactBackstoryId']: r for r in rows['ContactBackstory']}

    def plan(self, bid, offer):
        if bid not in CONVERSATIONS:
            raise ValueError('No reviewed New Game event for Backstory ' + str(bid))
        intro_id, followup_id = CONVERSATIONS[bid]
        intro, followup = self.by_id.get(intro_id), self.by_id.get(followup_id)
        entry = offer['StoryNode1']
        roots = {r['EventId'] for r in self.by_node[entry.removeprefix('ADD_')] if r['EventType'] == 'GroupFirst'}
        if not (intro and followup and intro['GroupId'] in roots):
            raise ValueError(f'Backstory {bid}: reviewed conversation is missing')
        traits = self.blocks[intro['EventId']]
        relations = self.blocks[followup['EventId']]
        if (intro['EventType'] != 'Choice' or followup['EventType'] != 'Choice'
                or len(traits) != 3 or len(relations) != 3
                or any(r['EventType'] != 'TalkOn' or r['EventId'] != followup['GroupId']
                       or not r['PostState3'].startswith('TRT_') for r in traits)):
            raise ValueError(f'Backstory {bid}: trait or follow-up choice layout changed')
        branches = []
        for relation in relations:
            path, seen = [], set()
            step = relation
            while step['EventType'] == 'TalkOn' and step['BlockId'] not in seen:
                path.append(step)
                seen.add(step['BlockId'])
                target = self.blocks[step['EventId']]
                if len(target) != 1:
                    raise ValueError(f'Backstory {bid}: ambiguous continuation at Block {step["BlockId"]}')
                step = target[0]
            endings = [r for r in self.blocks[step['EventId']] if r['ChoiceMeta'] == 6]
            if not path or step['EventType'] != 'Choice' or len(endings) != 1:
                raise ValueError(f'Backstory {bid}: reviewed hire ending changed')
            branches.append((path, step, endings[0]))
        for block in [intro, followup, *traits, *(b for path, end, _ in branches for b in [*path, end])]:
            if block['Dialog'] and not self.dialogs[block['Dialog']]:
                raise ValueError(f'Backstory {bid}: missing dialogue {block["Dialog"]}')
        return intro, traits, followup, branches

    def contact(self, action):
        if action['ConditionValue'] == -1:
            candidates = self.contacts[action['ConditionValue2']]
            contact = candidates[0] if len(candidates) == 1 else None
        else:
            contact = self.contact_ids.get(action['ConditionValue'])
        if not (contact and contact['TagID']):
            raise ValueError(f'BlockCondition {action["BlockConditionId"]}: contact identity needs review')
        return contact


def emit(stories, bid, backstory, offer, temporary, setup, prefix, base, add, condition, texts):
    """Emit one resumable safehouse event and its starter setup."""
    intro, traits, followup, branches = stories.plan(bid, offer)
    actor = backstory['CharStoryId']
    key = f'{prefix}_Finish_{bid}'
    node = node_id(prefix, bid)
    first, choices, follow, options, resume = [f'B_{key}_{name}' for name in
                                               ('Intro', 'Traits', 'Followup', 'Choices', 'Resume')]
    initial = [r for r in setup if r['ActorId'] != temporary or r['ConditionType'] != 'AddCharacter']
    paths = [b for path, _end, _finish in branches for b in path]
    action_rows = initial + [r for b in paths for field in ('PreDialogPostCondition', 'PostConditionGroup')
                             for r in stories.conditions[b[field]]]
    match_ids = list(dict.fromkeys([offer['EventId']] + [r['ConditionKey'] for r in action_rows
                                                          if r['ConditionType'] == 'StoryMatch']))
    bindings = {temporary: actor}
    cast_tags = {}
    cast_aliases = {}
    contact_actors = {}
    for row in action_rows:
        if row['ConditionType'] == 'AddCharacter':
            contact = stories.contact(row)
            identity = 'NTG_' + contact['TagID']
            bindings[row['ActorId']] = identity
            contact_actors[row['ActorId']] = contact['ContactStoryId'] or f'NCT_{key}_Contact_{contact["ContactBackstoryId"]}'
    for group in filter(None, match_ids):
        if not stories.matches[group]:
            raise ValueError(f'Backstory {bid}: missing casting group {group}')
        for row in stories.matches[group]:
            role = row['ActorId']
            if row['Optional'] == 3:
                contact = stories.contact_ids.get(row['Backstory'])
                if not (contact and contact['TagID'] and not row['RelationshipActorId']):
                    raise ValueError(f'Backstory {bid}: fixed casting role {role} needs review')
                bindings[role] = 'NTG_' + contact['TagID']
            elif role not in cast_tags:
                tag = f'{key}_Cast{len(cast_tags) + 1}'
                cast_tags[role] = tag
                bindings[role] = ('PTG_' if role.startswith('PCT_') else 'NTG_') + tag
                add('Tag', JsonId=base + len(cast_tags), TagId=tag, TagClass=1, Hide=1)
            if role not in cast_aliases:
                cast_aliases[role] = (role if role.startswith('NCP_') else
                                      role[:4] + key + '_Cast' + str(len(cast_aliases) + 1))

    if bid == 4004:
        # Dialog 10606–10607 name the transport contact with an obsolete alias.
        bindings['PCT_Recruit_Vanguard_HoverDrop'] = bindings['NCT_Recruit_Vanguard_Betray_Transport']

    aliases = re.compile('(?:' + '|'.join(map(re.escape, sorted(bindings, key=len, reverse=True))) + r')(?!\w)')

    def rebind(value):
        return aliases.sub(lambda match: bindings[match[0]], value) if isinstance(value, str) else value

    block_no = base
    match_no = base

    def block(group, **values):
        nonlocal block_no
        block_no += 1
        if block_no >= base + 256:
            raise ValueError(f'Backstory {bid}: starter event exceeds its reserved block range')
        return add('Block', BlockId=block_no, GroupId=group, **values)

    def action(group, kind, before='', **fields):
        row = block(group, PreConditionGroup=before)
        post = f'Post_{key}_{row["BlockId"]}'
        row['PostConditionGroup'] = post  # Serialized after all rows are authored.
        return condition(post, kind, **fields)

    def absent(suffix, identity):
        group = f'Pre_{key}_{suffix}'
        condition(group, 'HasCharacter', ActorId=identity, OptionId=-1)
        return group

    def copy_locale(old, new):
        for suffix in ('', '_Male', '_Female'):
            if old + suffix in stories.locale:
                texts[new + suffix] = stories.locale[old + suffix]

    copied_dialogs = {}

    def dialog(group):
        if group and group not in copied_dialogs:
            target = copied_dialogs[group] = f'D_{key}_{len(copied_dialogs) + 1}'
            for source in stories.dialogs[group]:
                values = {k: rebind(v) for k, v in source.items() if k not in ('DialogId', 'GroupId')}
                if any(re.search(r'(?:NCT|PCT)_\w+', values[k] or '') for k in ('ActorId', 'InterpolateActorId')):
                    raise ValueError(f'Backstory {bid}: unresolved temporary actor in Dialog {source["DialogId"]}')
                add('Dialog', GroupId=target, **values)
                copy_locale(f'Dialog.{group}.{source["JsonId"]}', f'Dialog.{target}.{source["JsonId"]}')
        return copied_dialogs.get(group, '')

    def copy_block(group, source, **changes):
        # The two stock intro wrappers track native offer progress. Starter
        # progress belongs to the mod's node, so carry presentation only here.
        fields = ('ActorId', 'InterpolateActorId', 'InterpolateId', 'InterpolateType', 'QuipType', 'DialogSide')
        values = {k: rebind(source[k]) for k in fields}
        values.update(changes)
        return block(group, **values)

    def native_conditions(group):
        return sorted(stories.conditions[group], key=lambda row: row['JsonId'])

    def cast(group, source_id):
        nonlocal match_no
        rows = stories.matches[source_id]
        dynamic = [r for r in rows if r['Optional'] != 3]
        batches = ([dynamic] if dynamic else []) + [[r] for r in rows if r['Optional'] == 3]
        for batch in batches:
            target = f'SM_{key}_{match_no - base + 1}'
            roles = list(dict.fromkeys(r['ActorId'] for r in batch))
            for r in batch:
                match_no += 1
                values = {k: rebind(v) for k, v in r.items() if k not in ('StoryMatchId', 'GroupId', 'ActorId')}
                add('StoryMatch', StoryMatchId=match_no, GroupId=target, ActorId=cast_aliases[r['ActorId']], **values)
            before = absent('Cast_' + str(match_no), bindings[roles[0]]) if batch[0]['Optional'] == 3 else ''
            post = action(group, 'StoryMatch', before, ConditionKey=target)['GroupId']
            for role in roles:
                alias = cast_aliases[role]
                if role in cast_tags:
                    condition(post, 'Tag', ActorId=alias, ConditionKey='ADD_' + cast_tags[role])
                if alias.startswith(('NCT_', 'PCT_')):
                    condition(post, 'TempStoryId', ActorId=alias, OptionId=-1, ConditionKey=alias)

    def operations(group, rows):
        for source in rows:
            kind = source['ConditionType']
            if kind not in OPERATIONS:
                raise ValueError(f'Backstory {bid}: unreviewed {kind} in BlockCondition {source["BlockConditionId"]}')
            if kind == 'StoryMatch':
                cast(group, source['ConditionKey'])
                continue
            values = {k: rebind(v) for k, v in source.items()
                      if k not in ('BlockConditionId', 'GroupId', 'JsonId', 'ConditionType')}
            before = ''
            if kind == 'AddCharacter':
                name = source['ActorId']
                before = absent('Contact_' + str(block_no + 1), bindings[name])
                values['ActorId'] = contact_actors[name]
            new = action(group, kind, before, **values)
            for part in ('Name', 'Desc'):
                copy_locale(f'BlockCondition.{part}.{source["GroupId"]}.{source["JsonId"]}',
                            f'BlockCondition.{part}.{new["GroupId"]}.{new["JsonId"]}')
            if kind == 'AddCharacter' and values['ActorId'].startswith('NCT_'):
                condition(new['GroupId'], 'TempStoryId', ActorId=values['ActorId'], OptionId=-1,
                          ConditionKey=values['ActorId'])

    start = setup_id(prefix, bid)
    if offer['EventId']:
        cast(start, offer['EventId'])
    # Create fixed contacts before their relationship tags are applied. The
    # Warmachine Sister's shipped group references Dr. Allgood before his add row.
    operations(start, sorted(initial, key=lambda r: r['ConditionType'] != 'AddCharacter'))
    # Some shipped starter templates have no supporting cast or setup actions.
    block(start)

    present = f'Pre_{key}_Present'
    condition(present, 'HasCharacter', ActorId=actor, OptionId=1)
    add('StoryNode', GroupId=node, StoryNodeId=node, StoryNodeType='Regular', ActorId=actor)
    link = block(f'B_{key}_Timeline', StoryNodeId=node, EventType='GroupFirst', EventId=resume,
                 ActorId=actor, InterpolateActorId=actor, ChoiceMeta=5,
                 PreConditionGroup=present, PreState1='HAS_Origin_Completed', PreState2=f'NOT_{key}_Done')
    for variant in ('Male', 'Female'):
        texts[f'BlockDesc.{link["BlockId"]}_{variant}'] = 'Finish Backstory: {1}'

    finish = f'B_{key}_Finish'
    _path, closing, native_finish = branches[0]
    if any(end['BlockId'] != closing['BlockId'] or last['BlockId'] != native_finish['BlockId']
           for _path, end, last in branches):
        raise ValueError(f'Backstory {bid}: branch ending needs review')
    ending = block(finish, ActorId='PCP_Knight', ChoiceMeta=-1, PostState1=f'ADD_{key}_Done',
                   StoryNode1='DEL_' + node)
    texts[f'BlockDesc.{ending["BlockId"]}'] = 'Finish'
    # The Vanguard's combined hire/reject cleanup contains three purge rows.
    # Starter setup can reuse those contacts, so only carry story bonuses.
    retain = [r for r in native_conditions(native_finish['PostConditionGroup'])
              if r['ConditionType'] not in ('Recruit', 'TempStoryId')
              and (bid, r['BlockConditionId']) not in {(4004, 169), (4004, 170), (4004, 171)}]
    if any(r['ConditionType'] != 'Boost' for r in retain):
        raise ValueError(f'Backstory {bid}: hiring finalizer needs review')
    if retain or cast_tags:
        post = ending['PostConditionGroup'] = f'Post_{key}_Finish'
        for r in retain:
            fields = {k: rebind(v) for k, v in r.items()
                      if k not in ('BlockConditionId', 'GroupId', 'JsonId', 'ConditionType')}
            condition(post, r['ConditionType'], **fields)
        for role, tag in cast_tags.items():
            condition(post, 'Tag', ActorId=bindings[role], ConditionKey='DEL_' + tag)

    for path, _closing, _ending in branches:
        source = path[0]
        index = source['BlockId']
        picked, completed = f'{key}_Choice_{index}', f'{key}_Applied_{index}'
        play, wrap = f'B_{key}_Play_{index}', f'B_{key}_Wrap_{index}'
        block(resume, EventType='Group', EventId=wrap, PreState1='HAS_' + completed)
        block(resume, EventType='Group', EventId=play, PreState1='HAS_' + picked)
        choice = copy_block(options, source, EventType='Group', EventId=play, PostState1='ADD_' + picked)
        copy_locale(f'BlockDesc.{index}', f'BlockDesc.{choice["BlockId"]}')
        pre = native_conditions(source['PreDialogPostCondition'])
        post = native_conditions(source['PostConditionGroup'])
        if index == 91099:
            # Cast the transport contact before the two lines that name them.
            cast_transport = [r for r in post if r['BlockConditionId'] == 174]
            if len(cast_transport) != 1:
                raise ValueError('Vanguard Betray transport casting needs review')
            pre += cast_transport
            post = [r for r in post if r not in cast_transport]
        if pre:
            ready = f'{key}_Prepared_{index}'
            prepare = f'B_{key}_Prepare_{index}'
            block(play, EventType='Group', EventId=prepare, PreState1='NOT_' + ready)
            operations(prepare, pre)
            block(prepare, PostState1='ADD_' + ready)
        commit = f'B_{key}_Commit_{index}'
        if any(b['PreConditionGroup'] or b['PreState1'] or b['PreState2'] or b['PostState1'] or b['PostState2']
               for b in path):
            raise ValueError(f'Backstory {bid}: branch state needs review at Block {index}')
        copy_block(play, source, EventType='TalkOn', EventId=commit, Dialog=dialog(source['Dialog']),
                   PostState3=source['PostState3'])
        apply = f'B_{key}_Apply_{index}'
        block(commit, EventType='Group', EventId=apply, PreState1='NOT_' + completed)
        operations(apply, post)
        block(apply, EventType='Group', EventId=wrap, PostState1='ADD_' + completed)
        target = wrap
        for step in path[1:]:
            if step['PreDialogPostCondition'] or step['PostConditionGroup'] or step['PostState3']:
                raise ValueError(f'Backstory {bid}: extra branch effects need review at Block {step["BlockId"]}')
            next_group = f'B_{key}_Line_{step["BlockId"]}'
            copy_block(target, step, EventType='TalkOn', EventId=next_group, Dialog=dialog(step['Dialog']))
            target = next_group
        copy_block(target, closing, EventType='Choice', EventId=finish, Dialog=dialog(closing['Dialog']))

    block(resume, EventType='Group', EventId=follow, PreState1=f'HAS_{key}_Trait')
    block(resume, EventType='Group', EventId=first)
    # The original recruitment greeting assumes the merc has yet to join.
    greeting = block(first, ActorId=actor, EventType='Choice', EventId=choices)
    texts[f'BlockDesc.{greeting["BlockId"]}'] = 'Before we go any further, there are a few things you should know about me.'
    for r in traits:
        if r['PreConditionGroup'] or r['PreDialogPostCondition'] or r['PostConditionGroup']:
            raise ValueError(f'Backstory {bid}: trait option effects need review')
        choice = copy_block(choices, r, EventType='TalkOn', EventId=follow, Dialog=dialog(r['Dialog']),
                            PreState1=f'NOT_{key}_Trait', PostState1=f'ADD_{key}_Trait', PostState3=r['PostState3'])
        copy_locale(f'BlockDesc.{r["BlockId"]}', f'BlockDesc.{choice["BlockId"]}')
    copy_block(follow, followup, EventType='Choice', EventId=options, Dialog=dialog(followup['Dialog']))


def verify_events(connection, scope, prefix, document):
    blocks = [dict(r) for r in connection.execute('SELECT * FROM Block')]
    by_group = groups(blocks)
    by_node = groups(blocks, 'StoryNodeId')
    actions = groups(dict(r) for r in connection.execute('SELECT * FROM BlockCondition'))
    templates = {r['BackstoryId']: dict(r) for r in connection.execute('SELECT * FROM Backstory')}
    nodes = {r['StoryNodeId']: dict(r) for r in connection.execute('SELECT * FROM StoryNode')}
    for bid in scope:
        node = node_id(prefix, bid)
        key = f'{prefix}_Finish_{bid}'
        actor = templates[bid]['CharStoryId']
        included = document['hub'][str(bid)]['include']
        starters = [b for b in blocks if 'ADD_' + node in (b['StoryNode1'], b['StoryNode2'], b['StoryNode3'])]
        owned = [b for b in blocks if b['GroupId'].startswith(f'B_{key}_')]
        if not included:
            if starters or owned or node in nodes:
                raise ValueError(f'Excluded Hub recruit has a starter event: {bid}')
            continue
        if (len(starters) != 1 or starters[0]['GroupId'] != f'B_{prefix}_Start_{bid}'
                or starters[0]['EventId'] != setup_id(prefix, bid)
                or starters[0]['PreState1'] != f'NOT_{key}_Queued'
                or starters[0]['PostState2'] != f'ADD_{key}_Queued'):
            raise ValueError(f'Backstory {bid}: the starter template must own activation exclusively')
        timeline = by_node[node]
        if (len(timeline) != 1 or node not in nodes or nodes[node]['ExpirationTurns']
                or nodes[node]['OnAddedBlock'] or nodes[node]['ExpirationBlock']):
            raise ValueError(f'Backstory {bid}: missing or expiring safehouse prompt')
        entry = timeline[0]
        if (entry['PreState1'] != 'HAS_Origin_Completed' or entry['PreState2'] != f'NOT_{key}_Done'
                or entry['ChoiceMeta'] != 5 or entry['ActorId'] != actor
                or [(r['ConditionType'], r['ActorId'], r['OptionId']) for r in actions[entry['PreConditionGroup']]]
                != [('HasCharacter', actor, 1)]):
            raise ValueError(f'Backstory {bid}: safehouse roster guard is missing')
        reached = set()

        def visit(target):
            if target in reached:
                return
            if not target.startswith(f'B_{key}_') or target not in by_group:
                raise ValueError(f'Backstory {bid}: event routes outside its namespace to {target}')
            reached.add(target)
            for step in by_group[target]:
                for field in ('PreConditionGroup', 'PreDialogPostCondition', 'PostConditionGroup'):
                    for op in actions[step[field]]:
                        if op['ConditionType'] in ('Recruit', 'Purge') or (op['ConditionType'] == 'AddCharacter'
                                and (op['ActorId'].startswith(('PCP_', 'PCT_'))
                                     or not any(r['ConditionType'] == 'HasCharacter' and r['OptionId'] == -1
                                                for r in actions[step['PreConditionGroup']]))):
                            raise ValueError(f'Backstory {bid}: unsafe or unguarded action on a starter path')
                if step['EventType'] in ('Group', 'GroupFirst', 'Choice', 'TalkOn'):
                    visit(step['EventId'])

        visit(starters[0]['EventId'])
        visit(entry['EventId'])
        finish = by_group[f'B_{key}_Finish']
        if (reached | {entry['GroupId']}) != {r['GroupId'] for r in owned} or len(finish) != 1:
            raise ValueError(f'Backstory {bid}: starter dialogue path is incomplete')
        if finish[0]['StoryNode1'] != 'DEL_' + node or finish[0]['PostState1'] != f'ADD_{key}_Done':
            raise ValueError(f'Backstory {bid}: finishing must close the prompt')
        for suffix in ('Traits', 'Choices'):
            if len(by_group[f'B_{key}_{suffix}']) != 3:
                raise ValueError(f'Backstory {bid}: missing a shipped choice in {suffix}')
        if any(not r['PostState3'].startswith('TRT_') or r['PreState1'] != f'NOT_{key}_Trait'
               or r['PostState1'] != f'ADD_{key}_Trait' for r in by_group[f'B_{key}_Traits']):
            raise ValueError(f'Backstory {bid}: trait checkpoint is missing')
        gates = [r['PreState1'] for r in by_group[entry['EventId']]]
        for choice in by_group[f'B_{key}_Choices']:
            suffix = choice['EventId'].rsplit('_', 1)[1]
            applied, picked = f'{key}_Applied_{suffix}', f'{key}_Choice_{suffix}'
            if (choice['PostState1'] != 'ADD_' + picked or 'HAS_' + picked not in gates
                    or 'HAS_' + applied not in gates or gates.index('HAS_' + applied) > gates.index('HAS_' + picked)
                    or [r['PreState1'] for r in by_group[f'B_{key}_Commit_{suffix}']] != ['NOT_' + applied]
                    or sum(r['PostState1'] == 'ADD_' + applied for r in by_group[f'B_{key}_Apply_{suffix}']) != 1):
                raise ValueError(f'Backstory {bid}: follow-up cannot resume safely')
