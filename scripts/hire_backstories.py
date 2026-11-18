"""Starter-only adaptations of the reviewed Underworld Hub conversations."""
from collections import defaultdict
import re

import hire_backstory_copy

# BackstoryId -> (trait prompt, follow-up prompt). These anchors are reviewed
# individually. A different conversation needs review before it can ship.
CONVERSATIONS = {
    4000: (91011, 91016), 4003: (91071, 91076), 4004: (91091, 91096),
    4005: (91111, 91116), 4006: (91131, 91136), 4008: (91192, 91197),
    4009: (91212, 91217), 4011: (91231, 91236), 4012: (91251, 91256),
    4013: (91270, 91275), 4014: (91290, 91295), 4015: (91313, 91318),
    4016: (91335, 91340), 305000: (305006, 305011), 305100: (305106, 305111),
}
STORY_TABLES = ('Block', 'BlockCondition', 'Dialog', 'StoryMatch', 'ContactBackstory', 'Tag')
OPERATIONS = {'AddCharacter', 'StoryMatch', 'Tag', 'Trait', 'Obligation', 'Item', 'CharacterStatus', 'PayRate'}
RECRUITMENT_QUIPS = {'Recruit_Global_FaceThink', 'Recruit_Global_DefineTrust'}
CONTACT_FALLBACKS = {4004: 8, 4005: 8, 4006: 9, 4008: 9, 4009: 8, 4012: 9, 305100: 9}
# These backstories reference undefined identity tags. Their permanent actor
# IDs and these authored tags also resolve contacts from earlier exports.
CONTACT_PRESENCE_TAGS = {2009: 'Tag_Gambler', 2022: 'Tag_StreetDocScammer'}
# These replies name the survivor directly instead of using an actor token.
NAMED_SURVIVORS = {91276: 'NCP_Recruit_Sniper_BestShot_Raven',
                   91277: 'NCP_Recruit_Sniper_BestShot_Kelsen',
                   91278: 'NCP_Recruit_Sniper_BestShot_Ryka'}
BLOCKS_PER_BACKSTORY = 48
FIRST_ID, LAST_ID = 567000, 567999


def mod_id(name):
    return f'{name}_HireEveryone'


def node_id(bid):
    return mod_id(f'SN_Finish_{bid}')


def setup_id(bid):
    return mod_id(f'B_Finish_{bid}_Setup')


def deadline(index):
    return 4 + index % 4


def permanent_contact_actor(contact, key):
    actor = contact['ContactStoryId']
    return actor if actor.startswith('NCP_') else mod_id(f'NCP_{key}_Contact_{contact["ContactBackstoryId"]}')


def contact_identity(contact, permanent_actor, tags):
    tag = contact['TagID']
    if tag and tag in tags:
        return 'NTG_' + tag, tag
    tag = CONTACT_PRESENCE_TAGS.get(contact['ContactBackstoryId'])
    if (not permanent_actor.startswith('NCP_') or tag not in tags
            or tag not in (contact['Tag1'], contact['Tag2'], contact['Tag3'])):
        raise ValueError(f'ContactBackstory {contact["ContactBackstoryId"]}: no usable identity check')
    return permanent_actor, tag


def contact_presence(condition, group, identity, tag, exists):
    # HasCharacter uses the player roster reader even for a contact's actor ID.
    condition(group, 'Tag', ActorId=identity, ConditionKey=tag, OptionId=1 if exists else -1)


def groups(rows, field='GroupId'):
    indexed = defaultdict(list)
    for row in rows:
        indexed[row[field]].append(row)
    return indexed


def check_coverage(stories, backstory, entry, base, turns):
    """Compile the event's rows in memory to report per-character authoring issues."""
    offer, main, setup = entry
    if offer['PreConditionGroup']:
        raise ValueError(f'Hub offer {offer["BlockId"]} has an unreviewed precondition')
    counts = defaultdict(int)

    def condition(group, kind, **fields):
        counts[group] += 1
        return dict(fields, GroupId=group, ConditionType=kind, JsonId=counts[group])

    emit(stories, backstory['BackstoryId'], backstory, offer, main['ActorId'], setup, base, turns,
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
        self.tags = {r['TagId'] for r in rows['Tag']}

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


def emit(stories, bid, backstory, offer, temporary, setup, base, turns, add, condition, texts):
    """Emit one resumable safehouse event and its starter setup."""
    _intro, traits, followup, branches = stories.plan(bid, offer)
    actor = backstory['CharStoryId']
    key = f'Finish_{bid}'
    node = node_id(bid)
    retry = mod_id(f'SN_{key}_Retry')
    choices, follow, options, prompts = [mod_id(f'B_{key}_{name}') for name in
                                         ('Traits', 'Followup', 'Choices', 'Prompts')]
    done, trained = mod_id(f'{key}_Done'), mod_id(f'{key}_Trait')
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
    contact_tags = {}
    fixed_cast = {}
    fallback_cast = {}

    def bind_contact(role, contact):
        cid = contact['ContactBackstoryId']
        permanent = permanent_contact_actor(contact, key)
        identity, tag = contact_identity(contact, permanent, stories.tags)
        bindings[role] = identity
        contact_tags[identity] = tag
        contact_actors[role] = (mod_id(f'NCT_{key}_Contact_{cid}')
                                if identity.startswith('NTG_') and not contact['ContactStoryId'] else permanent)

    for row in action_rows:
        if row['ConditionType'] == 'AddCharacter':
            bind_contact(row['ActorId'], stories.contact(row))
    for group in filter(None, match_ids):
        if not stories.matches[group]:
            raise ValueError(f'Backstory {bid}: missing casting group {group}')
        for row in stories.matches[group]:
            role = row['ActorId']
            if row['Optional'] == 3:
                contact = stories.contact_ids.get(row['Backstory'])
                if (not contact or not contact['TagID'] or contact['BlockGroup']
                        or any(row[k] for k in ('PreCond', 'PostStatus', 'RelationshipActorId', 'TagMatchActor',
                                                 'PostLink', 'PostLink2', 'PostState', 'PostState2', 'PostState3'))):
                    raise ValueError(f'Backstory {bid}: fixed casting role {role} needs review')
                bind_contact(role, contact)
                fixed_cast[row['StoryMatchId']] = contact
                continue
            elif role not in cast_tags:
                tag = mod_id(f'{key}_Cast{len(cast_tags) + 1}')
                cast_tags[role] = tag
                bindings[role] = ('PTG_' if role.startswith('PCT_') else 'NTG_') + tag
                add('Tag', JsonId=base + len(cast_tags), TagId=tag, TagClass=1, Hide=1)
            if role not in cast_aliases:
                cast_aliases[role] = (role if role.startswith('NCP_') else
                                      mod_id(role[:4] + key + '_Cast' + str(len(cast_aliases) + 1)))

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
        if block_no > base + BLOCKS_PER_BACKSTORY:
            raise ValueError(f'Backstory {bid}: starter event exceeds its reserved block range')
        return add('Block', BlockId=block_no, GroupId=group, **values)

    def absent(suffix, identity):
        group = mod_id(f'Pre_{key}_{suffix}')
        contact_presence(condition, group, identity, contact_tags[identity], False)
        return group

    def copy_locale(old, new):
        for suffix in ('', '_Male', '_Female'):
            key = old + suffix
            if key in stories.locale:
                text = stories.locale[key]
                texts[new + suffix] = hire_backstory_copy.edit(key, text) if old.startswith(('Dialog.', 'BlockDesc.')) else text

    copied_dialogs = {}

    def dialog(*parts):
        if parts not in copied_dialogs:
            target = copied_dialogs[parts] = mod_id(f'D_{key}_{len(copied_dialogs) + 1}')
            lines = [(group, row) for group in parts
                     for row in sorted(stories.dialogs[group], key=lambda r: r['JsonId'])]
            if parts == (followup['Dialog'],):
                # Some offers spell these lines out, while newer ones use stock quips.
                def recruitment_line(source):
                    group, row = source
                    loc = f'Dialog.{group}.{row["JsonId"]}'
                    variants = [stories.locale.get(loc + suffix, '').strip().casefold()
                                for suffix in ('', '_Male', '_Female')]
                    return (row['QuipType'] in RECRUITMENT_QUIPS
                            or 'what do you think, {1}?' in variants
                            or any('if you want in this company, trust is our baseline' in line for line in variants))

                lines = [line for line in lines if not recruitment_line(line)]
            if not lines:
                raise ValueError(f'Backstory {bid}: empty reply {parts}')
            for number, (group, source) in enumerate(lines, FIRST_ID):
                values = {k: rebind(v) for k, v in source.items() if k not in ('DialogId', 'GroupId', 'JsonId')}
                if any(re.search(r'(?:NCT|PCT)_\w+', values[k] or '') for k in ('ActorId', 'InterpolateActorId')):
                    raise ValueError(f'Backstory {bid}: unresolved temporary actor in Dialog {source["DialogId"]}')
                add('Dialog', GroupId=target, JsonId=number, **values)
                copy_locale(f'Dialog.{group}.{source["JsonId"]}', f'Dialog.{target}.{number}')
        return copied_dialogs[parts]

    def copy_block(group, source, **changes):
        # The two stock intro wrappers track native offer progress. Starter
        # progress belongs to the mod's node, so carry presentation only here.
        fields = ('ActorId', 'InterpolateActorId', 'InterpolateId', 'InterpolateType', 'QuipType', 'DialogSide')
        values = {k: rebind(source[k]) for k in fields}
        values.update(changes)
        return block(group, **values)

    def native_conditions(group):
        return sorted(stories.conditions[group], key=lambda row: row['JsonId'])

    def cast(source_id):
        nonlocal match_no
        rows = stories.matches[source_id]
        dynamic = [r for r in rows if r['Optional'] != 3]
        if dynamic:
            target = mod_id(f'SM_{key}_{match_no - base + 1}')
            roles = list(dict.fromkeys(r['ActorId'] for r in dynamic))
            for r in dynamic:
                match_no += 1
                values = {k: rebind(v) for k, v in r.items() if k not in ('StoryMatchId', 'GroupId', 'ActorId')}
                add('StoryMatch', StoryMatchId=match_no, GroupId=target, ActorId=cast_aliases[r['ActorId']], **values)
            effects = [('StoryMatch', {'ConditionKey': target}, None)]
            for role in roles:
                alias = cast_aliases[role]
                if role in cast_tags:
                    effects.append(('Tag', {'ActorId': alias, 'ConditionKey': 'ADD_' + cast_tags[role]}, None))
                if alias.startswith(('NCT_', 'PCT_')):
                    effects.append(('TempStoryId', {'ActorId': alias, 'OptionId': -1, 'ConditionKey': alias}, None))
            contact_roles = [role for role in roles if role.startswith('NC')]
            if contact_roles:
                fallback = stories.contact_ids.get(CONTACT_FALLBACKS.get(bid))
                if (len(roles) != 1 or not fallback or fallback['NewGame'] != 1 or fallback['Status'] != 1
                        or not fallback['ContactStoryId'] or not cast_tags.get(roles[0])):
                    raise ValueError(f'Backstory {bid}: cast needs a guaranteed New Game contact')
                role = roles[0]
                contact_tags[bindings[role]] = cast_tags[role]
                fallback_cast[target] = bindings[role], fallback['ContactStoryId'], cast_tags[role]
            yield '', effects
        for row in rows:
            if row['Optional'] != 3:
                continue
            # Native offers may match any eligible contact and use its temporary
            # actor ID. Our dialogue uses the specific backstory's identity tag.
            contact = fixed_cast[row['StoryMatchId']]
            role = row['ActorId']
            identity = bindings[role]
            fields = {'ActorId': contact_actors[role], 'ConditionValue': contact['ContactBackstoryId']}
            effects = contact_creation(fields, None)
            if row['TagMatch'] in stories.tags:
                effects.append(('Tag', {'ActorId': identity, 'ConditionKey': 'ADD_' + row['TagMatch']}, None))
            yield identity, effects

    def contact_creation(fields, source):
        effects = [('AddCharacter', fields, source)]
        actor_id = fields['ActorId']
        if actor_id.startswith('NCT_'):
            effects.append(('TempStoryId', {'ActorId': actor_id, 'OptionId': -1, 'ConditionKey': actor_id}, None))
        return effects

    def operation_batches(rows):
        for source in rows:
            kind = source['ConditionType']
            if kind not in OPERATIONS:
                raise ValueError(f'Backstory {bid}: unreviewed {kind} in BlockCondition {source["BlockConditionId"]}')
            if kind == 'StoryMatch':
                yield from cast(source['ConditionKey'])
                continue
            values = {k: rebind(v) for k, v in source.items()
                      if k not in ('BlockConditionId', 'GroupId', 'JsonId', 'ConditionType')}
            identity = ''
            if kind == 'AddCharacter':
                name = source['ActorId']
                identity = bindings[name]
                values['ActorId'] = contact_actors[name]
            effects = contact_creation(values, source) if identity else [(kind, values, source)]
            yield identity, effects

    def write_effects(group, effects):
        for kind, fields, source in effects:
            new = condition(group, kind, **fields)
            if source:
                for part in ('Name', 'Desc'):
                    copy_locale(f'BlockCondition.{part}.{source["GroupId"]}.{source["JsonId"]}',
                                f'BlockCondition.{part}.{new["GroupId"]}.{new["JsonId"]}')

    start = setup_id(bid)
    # Create fixed contacts before their relationship tags are applied. The
    # Warmachine Sister's shipped group references Dr. Allgood before his add row.
    setup_batches = list(cast(offer['EventId'])) if offer['EventId'] else []
    setup_batches.extend(operation_batches(sorted(initial, key=lambda r: r['ConditionType'] != 'AddCharacter')))
    repairs = []
    cast_retries = []
    for identity, effects in setup_batches:
        ordinal = str(block_no + 1)
        before = absent('Setup_' + ordinal, identity) if identity else ''
        post = mod_id(f'Post_{key}_Setup_{ordinal}')
        kind, fields, _ = effects[0]
        casting = fallback_cast.get(fields['ConditionKey']) if kind == 'StoryMatch' else None
        if casting:
            resolve = mod_id(f'B_{key}_Resolve_{ordinal}')
            cast_retries.append((resolve, post, *casting))
            block(start, EventType='Group', EventId=resolve)
        else:
            block(start, PreConditionGroup=before, PostConditionGroup=post)
        write_effects(post, effects)
        if identity:
            repairs.append((identity, post))
    # Some shipped starter templates have no supporting cast or setup actions.
    block(start)

    # The timeline skips untimed nodes. Expiry opens the same current prompt
    # and leaves an untimed roster entry in case the player closes the dialogue.
    prepare_contacts = bool(repairs or cast_retries)
    launch = mod_id(f'B_{key}_Launch') if prepare_contacts else prompts
    add('StoryNode', GroupId=node, StoryNodeId=node, StoryNodeType='Root',
        ExpirationTurns=turns, ExpirationBlock=launch, ExpirationStoryNode=retry)
    add('StoryNode', GroupId=node, StoryNodeId=retry, StoryNodeType='Regular')
    prompt = {'PreState1': 'HAS_Origin_Completed', 'PreState2': 'NOT_' + done}
    branch_ids = [path[0]['BlockId'] for path, _end, _finish in branches]
    no_choice = ['NOT_' + mod_id(f'{key}_Choice_{index}') for index in branch_ids]

    def gate(suffix, states, identity='', exists=False):
        group = mod_id(f'Pre_{key}_{suffix}')
        condition(group, 'HasCharacter', ActorId=actor, OptionId=1)
        for state in states:
            condition(group, 'GameState', ConditionKey=state)
        if identity:
            contact_presence(condition, group, identity, contact_tags[identity], exists)
        return group

    def describe(row, label):
        target = f'BlockDesc.{row["BlockId"]}'
        texts[target] = label
        if row['InterpolateActorId']:
            texts[target + '_Male'] = label
            texts[target + '_Female'] = label

    _path, closing, native_finish = branches[0]
    if any(end['BlockId'] != closing['BlockId'] or last['BlockId'] != native_finish['BlockId']
           for _path, end, last in branches):
        raise ValueError(f'Backstory {bid}: branch ending needs review')
    # The Vanguard's combined hire/reject cleanup contains three purge rows.
    # Starter setup can reuse those contacts, so only carry story bonuses.
    retain = [r for r in native_conditions(native_finish['PostConditionGroup'])
              if r['ConditionType'] not in ('Recruit', 'TempStoryId')
              and (bid, r['BlockConditionId']) not in {(4004, 169), (4004, 170), (4004, 171)}]
    if any(r['ConditionType'] != 'Boost' for r in retain):
        raise ValueError(f'Backstory {bid}: hiring finalizer needs review')
    cleanup = [('Boost', {k: rebind(v) for k, v in r.items()
                          if k not in ('BlockConditionId', 'GroupId', 'JsonId', 'ConditionType')}, r) for r in retain]
    cleanup.extend(('Tag', {'ActorId': bindings[role], 'ConditionKey': 'DEL_' + tag}, None)
                   for role, tag in cast_tags.items())

    visible_entry = gate('Entry', [])
    for active_node, meta, name in ((node, 5, 'Entry'), (retry, 4, 'Resume')):
        row = block(mod_id(f'B_{key}_{name}'), StoryNodeId=active_node,
                    ActorId=actor, InterpolateActorId=actor, ChoiceMeta=meta,
                    EventType='Group' if prepare_contacts else 'GroupFirst', EventId=launch,
                    PreConditionGroup=visible_entry, **prompt)
        describe(row, 'Finish Backstory: {1}')

    greeting = mod_id(f'D_{key}_Intro')
    add('Dialog', GroupId=greeting, JsonId=FIRST_ID, ActorId=actor, DisplaySide=1)
    texts[f'Dialog.{greeting}.{FIRST_ID}'] = 'Before we go any further, there are a few things you should know about me.'
    for step, dialog_id, target, trait in (('Intro', greeting, choices, 'NOT_'),
                                           ('Followup', dialog(followup['Dialog']), options, 'HAS_')):
        block(prompts, EventType='Choice', EventId=target, Dialog=dialog_id,
              PreConditionGroup=gate(step, [*no_choice, trait + trained]), **prompt)

    setup_contacts = {identity for identity, _ in repairs} | {r[2] for r in cast_retries}
    guaranteed = {c['ContactStoryId'] for c in stories.contact_ids.values()
                  if c['NewGame'] == 1 and c['ContactStoryId']}

    def contact_refs(rows):
        return {target for r in rows for col in ('ActorId', 'InterpolateActorId')
                if (target := rebind(r[col])).startswith(('NCP_', 'NCT_', 'NTG_'))}

    def require_contacts(available, needed, context):
        missing = needed - available - guaranteed
        if missing:
            raise ValueError(f'Backstory {bid}: {context} references unavailable contacts {sorted(missing)}')

    require_contacts(setup_contacts, contact_refs([followup, *traits]) | contact_refs(
        [row for part in [followup, *traits] for row in stories.dialogs[part['Dialog']]]), 'trait or follow-up')
    deferred_replies = []
    for path, _closing, _ending in branches:
        source = path[0]
        index = source['BlockId']
        picked, ready = mod_id(f'{key}_Choice_{index}'), mod_id(f'{key}_Prepared_{index}')
        pre = native_conditions(source['PreDialogPostCondition'])
        post = native_conditions(source['PostConditionGroup'])
        named = {rebind(NAMED_SURVIVORS[index])} if index in NAMED_SURVIVORS else set()
        reply_contacts = named | contact_refs([r for step in path for r in stories.dialogs[step['Dialog']]])
        before_ct = bool(pre) or index in (91019, 91099) or len(path) > 1
        require_contacts(setup_contacts, contact_refs([source]), f'option {index}')
        if any(b['PreConditionGroup'] or b['PreState1'] or b['PreState2'] or b['PostState1'] or b['PostState2']
               for b in path):
            raise ValueError(f'Backstory {bid}: branch state needs review at Block {index}')
        for step in path[1:]:
            if step['PreDialogPostCondition'] or step['PostConditionGroup'] or step['PostState3']:
                raise ValueError(f'Backstory {bid}: extra branch effects need review at Block {step["BlockId"]}')
        reply = dialog(*(step['Dialog'] for step in path))
        before, after = list(operation_batches(pre)), list(operation_batches(post))
        # Resolve a branch's contact before its first spoken line. Keep the
        # other branch effects on the choice's original completion side.
        create = [batch for batch in after if batch[0] in reply_contacts]
        before += create
        after = [batch for batch in after if batch not in create]
        require_contacts(setup_contacts | {identity for identity, _ in before}, reply_contacts, f'reply {index}')
        guarded = {identity for identity, _ in before + after if identity}
        if len(guarded) > 1:
            raise ValueError(f'Backstory {bid}: follow-up {index} needs multiple contact guards')
        identity = next(iter(guarded), '')
        cases = (False, True) if identity else (False,)

        def terminal(resuming, prepared, existing, contact, repair=False, *, index=index, source=source, reply=reply,
                     before=before, after=after, picked=picked, ready=ready):
            flags = ['HAS_' + picked] if resuming else [*no_choice, 'HAS_' + trained]
            if before:
                flags.append(('HAS_' if prepared else 'NOT_') + ready)
            ordinal = str(block_no + 1)
            start_post, end_post = mod_id(f'Post_{key}_Before_{ordinal}'), mod_id(f'Post_{key}_After_{ordinal}')
            # `Event` is the choice itself. Its response and the end-of-dialog
            # actions are handled by the same dialog player invocation.
            row = copy_block(prompts if resuming else options, source, EventType='Event', Dialog=reply,
                             PreConditionGroup=gate('Reply_' + ordinal, flags, contact, existing),
                             PreDialogPostCondition=start_post, PostConditionGroup=end_post,
                             PostState1='ADD_' + done, PostState3=source['PostState3'], StoryNode1='DEL_' + node,
                             StoryNode2='DEL_' + retry,
                             **(prompt if resuming else {}))
            copy_locale(f'BlockDesc.{index}', f'BlockDesc.{row["BlockId"]}')
            label = f'BlockDesc.{row["BlockId"]}'
            if label not in texts and not row['InterpolateActorId']:
                texts[label] = texts.get(label + '_Male') or texts.get(label + '_Female') or 'Continue the conversation.'
            if row['InterpolateActorId']:
                for variant in ('Male', 'Female'):
                    texts.setdefault(f'{label}_{variant}', texts.get(label) or 'Continue the conversation.')
            condition(start_post, 'GameState', ConditionKey='ADD_' + picked)
            if before and (not prepared or repair):
                for required, effects in before:
                    if (not required and not repair) or (required and not existing):
                        write_effects(start_post, effects)
                if not prepared:
                    condition(start_post, 'GameState', ConditionKey='ADD_' + ready)
            effects_after = [effect for required, effects in after if not required or not existing for effect in effects]
            effects_after.extend(cleanup)
            write_effects(end_post, effects_after)
            if not effects_after:
                row['PostConditionGroup'] = ''

        for exists in cases:
            terminal(False, False, exists, identity)
            terminal(True, False, exists, identity)
        if before:
            # A saved reply may already have executed its pre-dialog effects.
            # The tag-aware path repairs a missing contact without replaying
            # the other effects. Append new rows after the published blocks.
            if before_ct:
                terminal(True, True, True, identity)
            else:
                deferred_replies.append((terminal, True, identity, False))
            deferred_replies.append((terminal, False, identity, bool(identity)))

    for r in traits:
        if r['PreConditionGroup'] or r['PreDialogPostCondition'] or r['PostConditionGroup']:
            raise ValueError(f'Backstory {bid}: trait option effects need review')
        choice = copy_block(choices, r, EventType='TalkOn', EventId=follow, Dialog=dialog(r['Dialog']),
                            PreState1='NOT_' + trained, PostState1='ADD_' + trained, PostState3=r['PostState3'])
        copy_locale(f'BlockDesc.{r["BlockId"]}', f'BlockDesc.{choice["BlockId"]}')
    next_prompt = copy_block(follow, followup, EventType='Choice', EventId=options, Dialog=dialog(followup['Dialog']))
    describe(next_prompt, 'Tell me what happened next.')

    # Also retry on entry for an existing campaign whose starter setup ran
    # before the contact was fixed. Keep the existing conversation block IDs.
    for identity, post in repairs:
        before = gate(f'Restore_{block_no + 1}', [], identity)
        block(launch, PreConditionGroup=before, PostConditionGroup=post, **prompt)
    for resolve, _post, _identity, _fallback, _tag in cast_retries:
        block(launch, EventType='Group', EventId=resolve, PreConditionGroup=visible_entry, **prompt)
    if prepare_contacts:
        block(launch, EventType='GroupFirst', EventId=prompts, PreConditionGroup=visible_entry, **prompt)
    for terminal, exists, identity, repair in deferred_replies:
        if identity or exists:
            terminal(True, True, exists, identity, repair)
    for resolve, post, identity, fallback, tag in cast_retries:
        retry_cast = resolve.replace('_Resolve_', '_Fallback_')
        before = absent(f'Cast_{block_no + 1}', identity)
        block(resolve, PreConditionGroup=before, PostConditionGroup=post)
        block(resolve, EventType='GroupFirst', EventId=retry_cast)
        fallback_post = mod_id(f'Post_{key}_Fallback_{block_no + 1}')
        block(retry_cast, PreConditionGroup=before, PostConditionGroup=fallback_post)
        condition(fallback_post, 'Tag', ActorId=fallback, ConditionKey='ADD_' + tag)


def verify_events(connection, scope, document, locale=None):
    blocks = [dict(r) for r in connection.execute('SELECT * FROM Block')]
    by_group = groups(blocks)
    by_node = groups(blocks, 'StoryNodeId')
    actions = groups(dict(r) for r in connection.execute('SELECT * FROM BlockCondition'))
    templates = {r['BackstoryId']: dict(r) for r in connection.execute('SELECT * FROM Backstory')}
    nodes = {r['StoryNodeId']: dict(r) for r in connection.execute('SELECT * FROM StoryNode')}
    for index, bid in enumerate(scope):
        node = node_id(bid)
        key = f'Finish_{bid}'
        retry = mod_id(f'SN_{key}_Retry')
        prompt_group = mod_id(f'B_{key}_Prompts')
        launch = mod_id(f'B_{key}_Launch')
        repairs = by_group[launch]
        entry_target = launch if repairs else prompt_group
        trait_flag = mod_id(f'{key}_Trait')
        done = mod_id(f'{key}_Done')
        actor = templates[bid]['CharStoryId']
        included = document['hub'][str(bid)]['include']
        starters = [b for b in blocks if 'ADD_' + node in (b['StoryNode1'], b['StoryNode2'], b['StoryNode3'])]
        owned = [b for b in blocks if b['GroupId'].startswith(f'B_{key}_')]
        if not included:
            if starters or owned or node in nodes or retry in nodes:
                raise ValueError(f'Excluded Hub recruit has a starter event: {bid}')
            continue
        if (len(starters) != 1 or starters[0]['GroupId'] != mod_id(f'B_Start_{bid}')
                or starters[0]['EventId'] != setup_id(bid)
                or starters[0]['PreState1'] != 'NOT_' + mod_id(f'{key}_Queued')
                or starters[0]['PostState2'] != 'ADD_' + mod_id(f'{key}_Queued')):
            raise ValueError(f'Backstory {bid}: the starter template must own activation exclusively')
        if (node not in nodes or nodes[node]['StoryNodeType'] != 'Root' or nodes[node]['ActorId']
                or nodes[node]['ExpirationTurns'] != deadline(index) or nodes[node]['PauseMode']
                or nodes[node]['ExpirationBlock'] != entry_target or nodes[node]['ExpirationStoryNode'] != retry
                or retry not in nodes or nodes[retry]['ExpirationTurns'] or nodes[retry]['ExpirationBlock']):
            raise ValueError(f'Backstory {bid}: missing deadline or roster recovery')
        if repairs and (repairs[-1]['EventType'] != 'GroupFirst' or repairs[-1]['EventId'] != prompt_group):
            raise ValueError(f'Backstory {bid}: contact recovery must run before the conversation')
        initial_contacts = {b['PostConditionGroup'] for b in by_group[setup_id(bid)]
                            if any(r['ConditionType'] == 'AddCharacter' for r in actions[b['PostConditionGroup']])}
        if {b['PostConditionGroup'] for b in repairs[:-1] if b['PostConditionGroup']} != initial_contacts:
            raise ValueError(f'Backstory {bid}: contact recovery must cover each starter contact')
        entries = []
        for active_node, meta in ((node, 5), (retry, 4)):
            exposed = by_node[active_node]
            if len(exposed) != 1:
                raise ValueError(f'Backstory {bid}: expected one entry on {active_node}')
            entry = exposed[0]
            if (entry['PreState1'] != 'HAS_Origin_Completed' or entry['PreState2'] != 'NOT_' + done
                    or entry['ChoiceMeta'] != meta or entry['ActorId'] != actor
                    or len(by_group[entry['GroupId']]) != 1
                    or entry['EventType'] != ('Group' if repairs else 'GroupFirst') or entry['EventId'] != entry_target
                    or not any(r['ConditionType'] == 'HasCharacter' and r['ActorId'] == actor and r['OptionId'] == 1
                               for r in actions[entry['PreConditionGroup']])):
                raise ValueError(f'Backstory {bid}: incorrect safehouse entry for {active_node}')
            entries.append(entry)
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
                                and not op['ActorId'].startswith(('NCP_', 'NCT_'))):
                            raise ValueError(f'Backstory {bid}: unsafe action on a starter path')
                if step['EventType'] in ('Group', 'GroupFirst', 'Choice', 'TalkOn'):
                    visit(step['EventId'])

        visit(starters[0]['EventId'])
        for entry in entries:
            visit(entry['GroupId'])
        if reached != {r['GroupId'] for r in owned}:
            raise ValueError(f'Backstory {bid}: starter dialogue path is incomplete')
        replies = by_group[mod_id(f'B_{key}_Choices')]
        traits = by_group[mod_id(f'B_{key}_Traits')]
        prompts = by_group[prompt_group]
        if len(traits) != 3 or not replies:
            raise ValueError(f'Backstory {bid}: missing a shipped choice')
        endings = [*replies, *(r for r in prompts if r['EventType'] == 'Event')]
        if any(r['EventType'] != 'Event' or r['EventId'] or not r['Dialog'] or r['StoryNode1'] != 'DEL_' + node
               or r['StoryNode2'] != 'DEL_' + retry or r['PostState1'] != 'ADD_' + done for r in endings):
            raise ValueError(f'Backstory {bid}: the final choice must play its reply and close the prompt')
        if locale is not None:
            for row in endings + entries:
                loc = f'BlockDesc.{row["BlockId"]}'
                keys = [loc + '_Male', loc + '_Female'] if row['InterpolateActorId'] else [loc]
                if not all(locale.get(k) for k in keys):
                    raise ValueError(f'Backstory {bid}: missing visible label for {loc}')
        if any(not r['PostState3'].startswith('TRT_') or r['PreState1'] != 'NOT_' + trait_flag
               or r['PostState1'] != 'ADD_' + trait_flag for r in traits):
            raise ValueError(f'Backstory {bid}: trait checkpoint is missing')
        if any(r['ActorId'] or not r['Dialog'] for r in prompts if r['EventType'] == 'Choice'):
            raise ValueError(f'Backstory {bid}: the dialogue should open with its first authored line')
        check_availability(bid, key, actor, prompts, replies, actions)


def check_availability(bid, key, actor, prompts, replies, actions):
    """Check which generated rows can fire for each saved conversation state."""
    def choice_flag(row):
        return next(r['ConditionKey'][4:] for r in actions[row['PreDialogPostCondition']]
                    if r['ConditionType'] == 'GameState' and r['ConditionKey'].startswith(f'ADD_{key}_Choice_'))

    def visible(rows, states, actors):
        def state_allows(value):
            if not value:
                return True
            op, name = value.split('_', 1)
            return (name in states) == (op == 'HAS')

        def eligible(row):
            if not all(state_allows(row[name]) for name in ('PreState1', 'PreState2')):
                return False
            for cond in actions[row['PreConditionGroup']]:
                if cond['ConditionType'] == 'GameState' and not state_allows(cond['ConditionKey']):
                    return False
                if (cond['ConditionType'] in ('HasCharacter', 'Tag')
                        and (cond['ActorId'] in actors) != (cond['OptionId'] == 1)):
                    return False
            return True

        return [row for row in rows if eligible(row)]

    pending = {choice_flag(row) for row in replies}
    contacts = {r['ActorId'] for row in replies for r in actions[row['PreConditionGroup']]
                if r['ConditionType'] == 'Tag'}
    base = {'Origin_Completed'}
    second = base | {mod_id(key + '_Trait')}
    for present in ({actor}, {actor, *contacts}):
        first = visible(prompts, base, present)
        followup = visible(prompts, second, present)
        if (len(first) != 1 or first[0]['EventId'] != mod_id(f'B_{key}_Traits') or len(followup) != 1
                or followup[0]['EventId'] != mod_id(f'B_{key}_Choices')
                or visible(prompts, set(), present) or visible(prompts, base, set())
                or {choice_flag(row) for row in visible(replies, second, present)} != pending
                or len(visible(replies, second, present)) != 3):
            raise ValueError(f'Backstory {bid}: expected one safehouse prompt and three eligible follow-up choices')
        for picked in pending:
            prepared = picked.replace('_Choice_', '_Prepared_')
            for states in (second | {picked}, second | {picked, prepared}):
                resumed = visible(prompts, states, present)
                if len(resumed) != 1 or resumed[0]['EventType'] != 'Event' or choice_flag(resumed[0]) != picked:
                    raise ValueError(f'Backstory {bid}: pending follow-up {picked} cannot resume directly')
                if visible(prompts, states | {mod_id(key + '_Done')}, present):
                    raise ValueError(f'Backstory {bid}: completed follow-up {picked} offers another prompt')
