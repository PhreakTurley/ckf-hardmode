"""Positive service acquisition references from the selected official database.

This is an editor catalog policy, not a simulation of campaign choices. Contact
creation/starting links and ordinary PowerPlayService entries establish routes;
an unused service or contact template does not. No content ids are allowlisted.
"""


def routes(source, services):
    conditions = source.read('BlockConditionModel', ('BlockConditionId', 'GroupId', 'ConditionType',
        'ActorId', 'ConditionValue', 'ConditionValue2'))[1]
    blocks = source.read('BlockModel', ('Id', 'GroupId', 'PreConditionGroup', 'PostConditionGroup',
        'PreDialogPostCondition', 'Weight', 'EventType', 'EventOption', 'EventId',
        'StoryNode1', 'StoryNode2', 'StoryNode3'))[1]
    # DeveloperMode 1 requires developer mode; 2 is the shipped always-fail
    # declaration. -1 is the ordinary-player condition, not a disabled route.
    developer_groups = {r['GroupId'] for r in conditions
                        if r['ConditionType'] == 'DeveloperMode' and int(r['ConditionValue']) > 0}
    ordinary = [r for r in blocks if r['PreConditionGroup'] not in developer_groups]
    posts = {}
    for row in ordinary:
        for field in ('PostConditionGroup', 'PreDialogPostCondition'):
            if row[field]:
                posts.setdefault(row[field], []).append('Block ' + row['Id'])

    groups = {}

    def add(group, evidence):
        if group not in ('', '0', '-1'):
            refs = groups.setdefault(group, [])
            if evidence not in refs:
                refs.append(evidence)

    # AddCharacter -1 selects a new backstory group from ConditionValue2;
    # otherwise ConditionValue selects the group. NC actors are contacts;
    # player-character backstories have a separate identity space.
    contact_seeds = {}
    for row in conditions:
        if (row['ConditionType'] == 'AddCharacter' and row['ActorId'].startswith('NC')
                and row['GroupId'] in posts):
            group = row['ConditionValue2'] if row['ConditionValue'] in ('-1', '0') else row['ConditionValue']
            contact_seeds.setdefault(group, []).append('BlockCondition ' + row['BlockConditionId'])
    for row in source.read('BackstoryModel', ('BackstoryId', 'ContactLink1', 'ContactLink2', 'Weight'))[1]:
        if int(row['Weight']) > 0:
            for field in ('ContactLink1', 'ContactLink2'):
                contact_seeds.setdefault(row[field], []).append('Backstory %s.%s' % (row['BackstoryId'], field))
    matches = source.read('StoryMatchModel', ('StoryMatchId', 'GroupId', 'Backstory', 'ActorId', 'PreCond'))[1]
    called_matches = {r['EventId'] for r in ordinary}
    for row in matches:
        if (row['ActorId'].startswith('NC') and row['PreCond'] not in developer_groups
                and row['GroupId'] in called_matches):
            contact_seeds.setdefault(row['Backstory'], []).append('StoryMatch ' + row['StoryMatchId'])

    type_refs = {}
    slot_fields = tuple(field + str(i) for i in range(1, 4) for field in ('ServiceGroupId', 'ServiceLevel'))
    backstories = source.read('ContactBackstoryModel', ('ContactBackstoryId', 'BackstoryGroup', 'ContactType',
        'NewGame', 'Weight') + slot_fields)[1]
    for row in backstories:
        if int(row['Weight']) <= 0 or row['NewGame'] == '2':
            continue
        seeds = (['NewGame'] if row['NewGame'] == '1' else []) + contact_seeds.get(row['BackstoryGroup'], [])
        if not seeds:
            continue
        evidence = 'ContactBackstory %s (%s)' % (row['ContactBackstoryId'], ', '.join(seeds))
        type_refs.setdefault(row['ContactType'], []).append(evidence)
        for i in range(1, 4):
            if int(row['ServiceLevel' + str(i)]) > 0:
                add(row['ServiceGroupId' + str(i)], evidence)
    slot_fields = tuple(field + str(i) for i in range(1, 8) for field in ('ServiceGroupId', 'ServiceLevel'))
    for row in source.read('ContactTypeModel', ('ContactTypeId',) + slot_fields)[1]:
        if row['ContactTypeId'] in type_refs:
            evidence = 'ContactType %s via %s' % (row['ContactTypeId'], '; '.join(type_refs[row['ContactTypeId']]))
            for i in range(1, 8):
                if int(row['ServiceLevel' + str(i)]) > 0:
                    add(row['ServiceGroupId' + str(i)], evidence)

    # Explicit story grants to contacts also establish a contact-service route.
    # Only postconditions grant services; a precondition can merely test one.
    by_id = {r['ServiceTypeId']: r for r in services}
    for row in conditions:
        if row['GroupId'] not in posts or not row['ActorId'].startswith('NC'):
            continue
        if row['ConditionType'] == 'ContactServiceGroup' and int(row['ConditionValue']) > 0:
            add(row['ConditionValue'], 'BlockCondition ' + row['BlockConditionId'] + ' ContactServiceGroup')
        elif row['ConditionType'] == 'ContactService' and row['ConditionValue'] in by_id:
            add(by_id[row['ConditionValue']]['ServiceGroupId'],
                'BlockCondition ' + row['BlockConditionId'] + ' ContactService')

    nodes = {r['StoryNodeId'] for r in source.read('StoryNodeModel', ('StoryNodeId',))[1]}
    tags, blocked = {}, {}
    for row in blocks:
        if row['EventType'] != 'PowerPlayService':
            continue
        tag = row['EventOption']
        evidence = 'Block ' + row['Id'] + ' PowerPlayService'
        if row['PreConditionGroup'] in developer_groups:
            blocked.setdefault(tag, []).append(evidence + ' gated by ' + row['PreConditionGroup'])
            continue
        matching = [r for r in matches if r['GroupId'] == row['EventId']]
        starts = [row[f][4:] for f in ('StoryNode1', 'StoryNode2', 'StoryNode3') if row[f].startswith('ADD_')]
        if (int(row['Weight']) <= 0 or not matching or not starts or any(n not in nodes for n in starts)
                or any(r['PreCond'] in developer_groups for r in matching)):
            blocked.setdefault(tag, []).append(evidence + ' has no complete ordinary entry')
            continue
        tags.setdefault(tag, []).append(evidence)

    # A tag anywhere in a ladder identifies its Power Play route. Later tiers
    # need not repeat the acquisition tag declared on the entry tier.
    for row in services:
        for evidence in tags.get(row['PowerPlayTag'], []):
            add(row['ServiceGroupId'], evidence)
    return groups, blocked
