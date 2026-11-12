"""Service acquisition, independent contact routes, and live database refresh."""
from contextlib import closing
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import player_balance as pb
import static_data


class Source:
    locale = {}

    def __init__(self):
        self.tables = {name + 'Model': [] for name in ('ContactService', 'Block', 'BlockCondition',
            'StoryNode', 'StoryMatch', 'ContactType', 'ContactBackstory', 'Backstory')}

    def add(self, table, **fields):
        self.tables[table + 'Model'].append({k: str(v) for k, v in fields.items()})

    def read(self, model, required=(), **kwargs):
        rows = self.tables[model]
        for row in rows:
            assert set(required) <= row.keys(), (model, set(required) - row.keys())
        return list(required), [dict(r) for r in rows]

    def service(self, rid, group, option, flow=1, tag='', level=1, ready=0):
        self.add('ContactService', ServiceTypeId=rid, ServiceGroupId=group, ServiceOptionId=option,
            ServiceFlow=flow, PowerPlayTag=tag, ServiceLevel=level, DisplayLevel=level, UpgradeReady=ready)

    def contact(self, rid, group=0, ctype=0, newgame=0):
        self.add('ContactBackstory', ContactBackstoryId=rid, BackstoryGroup=rid, ContactType=ctype,
            NewGame=newgame, Weight=1, ServiceGroupId1=group, ServiceLevel1=1,
            ServiceGroupId2=0, ServiceLevel2=0, ServiceGroupId3=0, ServiceLevel3=0)

    def block(self, rid, gate='', post='', **fields):
        self.add('Block', **dict(dict(Id=rid, GroupId='Block_' + str(rid), PreConditionGroup=gate,
            PostConditionGroup=post, PreDialogPostCondition='', Weight=10, EventType='', EventOption='',
            EventId='', StoryNode1='', StoryNode2='', StoryNode3=''), **fields))

    def condition(self, rid, group, kind, actor='', value=0, value2=0):
        self.add('BlockCondition', BlockConditionId=rid, GroupId=group, ConditionType=kind,
            ActorId=actor, ConditionValue=value, ConditionValue2=value2)

    def power_play(self, tag, gate=''):
        self.block(40, gate=gate, EventType='PowerPlayService', EventOption=tag,
                   EventId='Match_Future', StoryNode1='ADD_SN_Future')
        self.add('StoryMatch', StoryMatchId=50, GroupId='Match_Future', Backstory=0,
                 ActorId='NCT_Future', PreCond='')
        self.add('StoryNode', StoryNodeId='SN_Future')


def services(source):
    return {r['ServiceTypeId']: r for r in pb.contact_services(source)}


class ServiceAvailabilityTests(unittest.TestCase):
    def test_unused_service_and_contact_templates_do_not_qualify(self):
        source = Source()
        source.service(1, 90, 20)
        source.contact(2, group=90)
        self.assertFalse(services(source)['1']['attainable'])
        source.block(3, post='Create')
        source.condition(4, 'Create', 'AddCharacter', 'NCP_Test', -1, 2)
        self.assertTrue(services(source)['1']['attainable'])
        source.tables['BlockModel'].clear()
        self.assertFalse(services(source)['1']['attainable'])

    def test_new_contact_type_and_merc_contact_link_establish_routes(self):
        source = Source()
        source.service(1, 90, 20)
        source.contact(2, ctype=3)
        slots = {k + str(n): (90 if k == 'ServiceGroupId' and n == 7 else 1 if k == 'ServiceLevel' else 0)
                 for n in range(1, 8) for k in ('ServiceGroupId', 'ServiceLevel')}
        source.add('ContactType', ContactTypeId=3, **slots)
        self.assertFalse(services(source)['1']['attainable'])
        source.add('Backstory', BackstoryId=4, ContactLink1=2, ContactLink2=0, Weight=1)
        self.assertTrue(services(source)['1']['attainable'])
        source.tables['ContactBackstoryModel'][0]['NewGame'] = '2'
        self.assertFalse(services(source)['1']['attainable'])

    def test_power_play_gate_changes_without_an_id_allowlist_and_propagates_to_tiers(self):
        source = Source()
        source.service(1, 90, 20, tag='FuturePowerPlay')
        source.service(2, 90, 21, level=2)
        source.power_play('FuturePowerPlay', 'Renamed_Developer_Gate')
        source.condition(3, 'Renamed_Developer_Gate', 'DeveloperMode', value=2)
        self.assertFalse(any(r['attainable'] for r in services(source).values()))
        self.assertIn('Renamed_Developer_Gate', services(source)['2']['unattainableReason'])
        source.tables['BlockConditionModel'][0]['ConditionValue'] = '-1'
        self.assertTrue(all(r['attainable'] for r in services(source).values()))
        source.tables['StoryNodeModel'].clear()
        self.assertFalse(any(r['attainable'] for r in services(source).values()))

    def test_contact_route_survives_disabled_power_play_but_not_tier_cap(self):
        source = Source()
        source.service(1, 90, 20, tag='Disabled', ready=2)
        source.service(2, 90, 21, level=2)
        source.power_play('Disabled', 'Never')
        source.condition(3, 'Never', 'DeveloperMode', value=2)
        source.contact(4, group=90, newgame=1)
        actual = services(source)
        self.assertTrue(actual['1']['attainable'])
        self.assertFalse(actual['2']['attainable'])
        self.assertIn('exceeds cap', actual['2']['unattainableReason'])

    def test_orphan_or_developer_only_story_matches_do_not_create_contact_routes(self):
        source = Source()
        source.service(1, 90, 20)
        source.contact(2, group=90)
        source.add('StoryMatch', StoryMatchId=3, GroupId='Match_Test', Backstory=2,
                   ActorId='NCP_Test', PreCond='')
        self.assertFalse(services(source)['1']['attainable'])
        source.block(4, gate='Dev', EventType='Match', EventId='Match_Test')
        source.condition(5, 'Dev', 'DeveloperMode', value=1)
        self.assertFalse(services(source)['1']['attainable'])
        source.tables['BlockModel'][0]['PreConditionGroup'] = ''
        self.assertTrue(services(source)['1']['attainable'])

    def test_story_service_grants_qualify_but_predicates_and_removals_do_not(self):
        source = Source()
        source.service(1, 90, 20)
        source.condition(2, 'HasService', 'ContactServiceGroup', 'NCT_Test', 90)
        source.block(3, gate='HasService')
        self.assertFalse(services(source)['1']['attainable'])
        source.block(4, post='Remove')
        source.condition(5, 'Remove', 'ContactServiceGroup', 'NCT_Test', -90)
        self.assertFalse(services(source)['1']['attainable'])
        source.block(6, post='Grant')
        source.condition(7, 'Grant', 'ContactService', 'NCT_Test', 1)
        self.assertTrue(services(source)['1']['attainable'])

    def test_shared_options_respect_flow_and_only_use_available_labels(self):
        source = Source()
        source.service(1, 90, 20)
        source.service(2, 91, 20)
        source.service(3, 92, 20, flow=8)
        source.contact(4, group=91, newgame=1)
        source.locale = {'ContactService.Name.1': 'Missing', 'ContactService.Name.2': 'Available',
                         'ContactService.Name.3': 'Other flow'}
        actual = pb.service_catalog(source)
        self.assertEqual(actual['Weapon']['20']['label'], 'Available · L1')
        self.assertTrue(actual['Weapon']['20']['attainable'])
        self.assertFalse(actual['Implant']['20']['attainable'])

    def test_official_contact_services_and_power_plays(self):
        with static_data.StaticData() as source:
            actual = services(source)
            for rid in ('6052', '6056', '13022', '13007', '13012', '13036'):
                self.assertTrue(actual[rid]['attainable'], actual[rid])
            self.assertTrue(any('ContactBackstory 7005' in s for s in actual['6052']['acquisition']))
            self.assertTrue(any('ContactBackstory 7006' in s for s in actual['6056']['acquisition']))
            for rid in ('13002', '13017', '13026', '13030', '13031', '13035'):
                self.assertFalse(actual[rid]['attainable'], actual[rid])
            refs = pb.player_gear_references(source)
            self.assertNotIn('ContactService 13028', refs['Weapon'].get('1022', []))

    def test_database_refresh_changes_catalog_without_deleting_saved_overrides(self):
        with tempfile.TemporaryDirectory() as temp, static_data.StaticData() as source:
            root = Path(temp)
            database = root / 'data.db'
            with closing(sqlite3.connect(database)) as db:
                source.connection.backup(db)
            doc = pb.empty()
            doc['tables'] = {'Weapon': {'1022': {'Cost': '123'}}}
            path = root / pb.FILE
            path.write_bytes(pb.encode(doc))
            original = path.read_bytes()

            def catalog():
                model = pb.catalog(root, database)
                self.assertIsNone(model['error'])
                self.assertEqual(path.read_bytes(), original)
                self.assertEqual(model['document'], doc)
                return [(p['id'], g, r) for p in model['pages'] for g in p['grids']
                        if g['table'] == 'Weapon' for r in g['rows'] if r['id'] == '1022']

            first = catalog()
            self.assertEqual([p for p, g, r in first], ['other-weapon-overrides'])
            with closing(sqlite3.connect(database)) as db:
                # An existing meetable contact gains the previously unused ladder.
                db.execute('UPDATE ContactBackstory SET ServiceGroupId1=13400 WHERE ContactBackstoryId=7005')
                db.commit()
            second = catalog()
            self.assertEqual([p for p, g, r in second], ['weapon-3'])
            self.assertTrue(second[0][1]['serviceColumn']['options']['13402']['attainable'])
            with closing(sqlite3.connect(database)) as db:
                db.execute('UPDATE ContactBackstory SET ServiceGroupId1=8000 WHERE ContactBackstoryId=7005')
                db.commit()
            self.assertEqual([p for p, g, r in catalog()], ['other-weapon-overrides'])


if __name__ == '__main__':
    unittest.main()
