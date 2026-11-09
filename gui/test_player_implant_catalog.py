"""Inclusive implant acquisition and preservation of unreachable overrides."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import player_balance as pb
import static_data


def implant(rid, option=0, klass=0, group=0, flag=0):
    return dict(zip(('ImplantTypeId', 'ServiceOptionId', 'ImplantClass', 'BackstoryGroup', 'Deactivated'),
                    map(str, (rid, option, klass, group, flag))))


def service(rid, flow, group, level, option, ready=0):
    return dict(zip(('ServiceTypeId', 'ServiceFlow', 'ServiceGroupId', 'ServiceLevel',
                     'ServiceOptionId', 'UpgradeReady', 'DisplayLevel'),
                    map(str, (rid, flow, group, level, option, ready, level))))


class Source:
    def __init__(self):
        self.data = {
            'ImplantModel': [implant(1, option=1), implant(2, option=2), implant(3), implant(4),
                implant(5, klass=50), implant(6, klass=50), implant(7, klass=60), implant(8, flag=9),
                implant(9), implant(10, flag=-1), implant(11, flag=-2), implant(12), implant(13, group=100),
                implant(14, group=999), implant(15, option=3), implant(16), implant(17),
                implant(18, option=1), implant(19, flag=19), implant(20, flag=999)],
            'ContactServiceModel': [service(100, 8, 1, 1, 1, ready=2), service(101, 8, 1, 2, 2),
                                    service(102, 1, 1, 1, 3)],
            'BackstoryModel': [{'BackstoryId': '16', 'BackstoryGroup': '100', 'Implant': '4',
                               'Implant1': '3', 'Implant2': '999', 'Implant3': '0'}],
            'JobModel': [{'JobId': '7', 'JobType': '1', 'ReqCyberClass1Id': '50', 'Enabled': '0'},
                         {'JobId': '8', 'JobType': '2', 'ReqCyberClass1Id': '60', 'Enabled': '1'}],
            'DronePrebuiltModel': [{'DroneType': '7', 'CyberSlot1': '12', 'CyberSlot2': '0',
                                   'CyberSlot3': '0', 'CyberSlot4': '0', 'CyberSlot5': '0'}],
            'BlockConditionModel': [{'BlockConditionId': '16', 'ConditionType': 'ActivateCyber'}],
        }

    def read(self, model, required=()):
        rows = self.data[model]
        assert all(set(required) <= r.keys() for r in rows), (model, required)
        return list(rows[0]) if rows else list(required), rows


class ImplantCatalogTests(unittest.TestCase):
    def test_sources_are_inclusive_typed_and_service_cap_aware(self):
        source, doc, kinds = Source(), pb.empty(), {}
        doc['tables'] = {'Implant': {'17': {'ServiceOptionId': '1'}, '18': {'ServiceOptionId': '0'}}}
        refs = pb.player_implant_references(source, doc, kinds)['Implant']
        self.assertEqual(set(refs), {'1', '3', '4', '5', '6', '8', '9', '10', '11', '12', '13', '17', '18', '19', '20'})
        self.assertEqual(kinds['Implant']['1'], {'service'})
        self.assertEqual(kinds['Implant']['5'], {'starting'})
        self.assertEqual(kinds['Implant']['11'], {'story'})
        self.assertIn('PetPrebuilt 7.CyberSlot1', refs['12'])
        self.assertTrue(any('ActivateCyber BlockCondition 16' in e for e in refs['8']))
        self.assertNotIn('16', refs)  # Backstory/event ids are not implant ids.
        self.assertNotIn('7', refs)   # Job/prebuilt ids are not implant ids.
        self.assertNotIn('999', refs)
        self.assertNotIn('2', refs)   # Above its own service cap.
        self.assertNotIn('15', refs)  # An option in the weapon flow cannot sell an implant.
        source.data['ContactServiceModel'].append(service(103, 8, 2, 1, 2))
        self.assertIn('ContactService 103', pb.player_implant_references(source)['Implant']['2'])

    def test_service_fallbacks_distinguish_starting_story_combined_and_service_only_sources(self):
        source, kinds = Source(), {}
        next(r for r in source.data['ImplantModel'] if r['ImplantTypeId'] == '5')['Deactivated'] = '-1'
        refs = pb.player_implant_references(source, source_kinds=kinds)
        labels = pb.implant_service_fallbacks(refs, kinds)
        self.assertEqual(labels['3']['label'], 'Starting Gear')
        self.assertEqual(labels['8']['label'], 'Mission')
        self.assertEqual(labels['5']['label'], 'Starting Gear / Mission')
        self.assertEqual(labels['1']['label'], '')
        self.assertIn('Backstory 16.Implant1', labels['3']['detail'])
        self.assertIn('Deactivated -1', labels['5']['detail'])

    def test_story_candidate_policy_does_not_fabricate_missing_activation_references(self):
        source = Source()
        source.data['BlockConditionModel'] = []
        refs = pb.player_implant_references(source)['Implant']
        self.assertIn('11', refs)
        self.assertFalse(any('ActivateCyber' in e for e in refs['11']))

    def test_official_filter_matches_independent_sql_for_all_sources(self):
        with tempfile.TemporaryDirectory() as config, static_data.StaticData() as source:
            expected = {str(r[0]) for r in source.connection.execute('''
                SELECT i.ImplantTypeId FROM Implant i WHERE
                  EXISTS (SELECT 1 FROM ContactService s WHERE s.ServiceFlow=8 AND s.ServiceOptionId>0
                          AND s.ServiceOptionId=i.ServiceOptionId
                          AND NOT EXISTS (SELECT 1 FROM ContactService cap WHERE cap.ServiceFlow=s.ServiceFlow
                              AND cap.ServiceGroupId=s.ServiceGroupId AND cap.UpgradeReady=2 AND cap.ServiceLevel<s.ServiceLevel))
                  OR EXISTS (SELECT 1 FROM Backstory b WHERE i.ImplantTypeId IN (b.Implant,b.Implant1,b.Implant2,b.Implant3))
                  OR (i.BackstoryGroup>0 AND EXISTS (SELECT 1 FROM Backstory b WHERE b.BackstoryGroup=i.BackstoryGroup))
                  OR EXISTS (SELECT 1 FROM Job j WHERE j.JobType=1 AND j.ReqCyberClass1Id>0 AND j.ReqCyberClass1Id=i.ImplantClass)
                  OR i.Deactivated<>0
                  OR EXISTS (SELECT 1 FROM Implant d WHERE d.Deactivated>0 AND d.Deactivated=i.ImplantTypeId)
                  OR EXISTS (SELECT 1 FROM PetPrebuilt p WHERE i.ImplantTypeId IN
                              (p.CyberSlot1,p.CyberSlot2,p.CyberSlot3,p.CyberSlot4,p.CyberSlot5))
            ''')}
            model = pb.catalog(config, static_data.DEFAULT_DB)
            self.assertIsNone(model['error'])
            rows = [r for p in model['pages'] for g in p['grids'] if g['table'] == 'Implant' for r in g['rows']]
            self.assertEqual({r['id'] for r in rows}, expected)
            self.assertEqual(len(rows), len(expected))
            self.assertTrue(all(r['acquisition'] for r in rows))
            self.assertFalse(any(p['id'] == 'other-cyberware-overrides' for p in model['pages']))
            self.assertTrue({'100', '2301', '1301', '3801', '10000', '10010'} <= expected)
            self.assertNotIn('10013', expected)

    def test_saved_native_overrides_move_between_other_main_and_hidden(self):
        import serve
        with tempfile.TemporaryDirectory() as config:
            (Path(config) / 'ckf.hardmode.cfg').write_text('', encoding='utf-8')
            app = serve.App({'configDirOverride': config}, 'test', static_source=static_data.DEFAULT_DB)
            model = app.api_model()
            for column, value, expected in [('Cost', '0', ['other-cyberware-overrides']),
                    ('ServiceOptionId', '1', ['implant-2']), ('ServiceOptionId', '', ['other-cyberware-overrides']),
                    ('Cost', '', [])]:
                saved = app.api_save({'playerBalance': {'databaseSha': model['playerBalance']['database']['sha256'],
                    'cells': [{'table': 'Implant', 'id': '700', 'column': column, 'value': value}]}}, expect=model['fingerprints'])
                self.assertTrue(saved['ok'], saved)
                model = app.api_model()
                locations = [p['id'] for p in model['playerBalance']['pages'] for g in p['grids']
                             if g['table'] == 'Implant' for r in g['rows'] if r['id'] == '700']
                self.assertEqual(locations, expected)
            self.assertEqual(pb.load(config), pb.empty())

    def test_linked_effect_overrides_remain_editable_until_the_last_reset(self):
        with tempfile.TemporaryDirectory() as config, static_data.StaticData() as source:
            doc = pb.apply_edits(pb.empty(), {'cells': [
                {'table': 'Implant', 'id': '10011', 'column': 'Cost', 'value': '17'},
                {'table': 'Effect', 'id': '59003', 'column': 'MaxHitPoints', 'value': '9'}]}, source)
            path = Path(config) / pb.FILE
            path.parent.mkdir(parents=True, exist_ok=True)
            for table, rid, col, present in [('Implant', '10011', 'Cost', True), ('Effect', '59003', 'MaxHitPoints', False)]:
                doc = pb.apply_edits(doc, {'cells': [{'table': table, 'id': rid, 'column': col, 'value': ''}]}, source)
                path.write_bytes(pb.encode(doc))
                model = pb.catalog(config, static_data.DEFAULT_DB)
                self.assertIsNone(model['error'])
                rows = [r for p in model['pages'] if p['id'] == 'other-cyberware-overrides'
                        for g in p['grids'] for r in g['rows'] if r['id'] == '10011']
                self.assertEqual(bool(rows), present)
                if present:
                    self.assertEqual(rows[0]['targets']['Effects.MaxHitPoints']['table'], 'Effect')
                    self.assertEqual(rows[0]['targets']['Effects.MaxHitPoints']['id'], '59003')
                    self.assertEqual(pb.load(config), doc)


if __name__ == '__main__':
    unittest.main()
