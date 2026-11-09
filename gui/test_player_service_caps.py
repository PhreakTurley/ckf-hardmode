"""Terminal service tiers, alternate acquisition, and retained overrides."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import player_balance as pb
import static_data


def service(rid, flow, group, level, option, ready='0', display=None):
    return {'ServiceTypeId': str(rid), 'ServiceFlow': str(flow), 'ServiceGroupId': str(group),
            'ServiceLevel': str(level), 'ServiceOptionId': str(option), 'UpgradeReady': str(ready),
            'DisplayLevel': str(level if display is None else display)}


class ServiceSource:
    def __init__(self, rows, source=None):
        self.rows, self.source = rows, source
        self.locale = source.locale if source else {}

    def read(self, model, required=(), **kwargs):
        if model == 'ContactServiceModel':
            assert all(set(required) <= r.keys() for r in self.rows)
            return list(self.rows[0]) if self.rows else list(required), self.rows
        return self.source.read(model, required, **kwargs)


class ServiceCapTests(unittest.TestCase):
    def test_caps_use_flow_group_and_internal_level_with_inclusive_boundary(self):
        rows = [service(1, 1, 10, 3, 3, display=99), service(2, 1, 10, 4, 4, ready=2),
                service(3, 1, 10, 5, 5), service(4, 1, 11, 6, 6),
                service(5, 3, 10, 6, 7), service(6, 1, 10, 6, 8, ready=2),
                service(7, 1, 10, 4, 9, ready=2)]
        result = {r['ServiceTypeId']: r for r in pb.contact_services(ServiceSource(rows))}
        self.assertEqual({rid: r['attainable'] for rid, r in result.items()},
                         {'1': True, '2': True, '3': False, '4': True, '5': True, '6': False, '7': True})
        self.assertEqual(result['3']['cap'], {'level': 4, 'ids': ['2', '7']})
        self.assertIn('ServiceLevel 5 exceeds cap 4', result['3']['unattainableReason'])
        self.assertIn('UpgradeReady=2', result['3']['unattainableReason'])

    def test_catalog_marks_blocked_services_without_losing_valid_shared_options(self):
        rows = [service(1, 3, 10, 4, 13, ready=2), service(2, 3, 10, 5, 14),
                service(3, 3, 11, 8, 14), service(4, 3, 10, 6, 15)]
        source = ServiceSource(rows)
        source.locale = {'ContactService.Name.' + r['ServiceTypeId']: 'Shop ' + r['ServiceTypeId'] for r in rows}
        options = pb.service_catalog(source)['WeaponMod']
        self.assertTrue(options['13']['attainable'])
        self.assertNotIn('Unattainable', options['13']['label'])
        self.assertTrue(options['14']['attainable'])
        self.assertEqual(options['14']['label'], 'Shop 3 · L8')
        self.assertEqual(options['15']['label'], '')
        self.assertFalse(options['15']['attainable'])
        self.assertIn('ContactService 1 has UpgradeReady=2', options['15']['detail'])

    def test_official_above_cap_services_cannot_establish_acquisition(self):
        with static_data.StaticData() as source:
            services = pb.service_catalog(source)
            self.assertFalse(services['WeaponMod']['14']['attainable'])
            self.assertFalse(services['WeaponMod']['15']['attainable'])
            self.assertTrue(services['WeaponMod']['13']['attainable'])
            self.assertFalse(services['Item']['103']['attainable'])
            self.assertTrue(services['Weapon']['4']['attainable'])
            refs = pb.player_gear_references(source)
            self.assertFalse({'1005', '5019', '6021', '8006'} & refs['WeaponMod'].keys())
            blocked = {r['ServiceTypeId'] for r in pb.contact_services(source) if not r['attainable']}
            self.assertFalse(any(e in {'ContactService ' + rid for rid in blocked}
                                 for records in refs.values() for evidence in records.values() for e in evidence))
            # An independently available service can use the same option id.
            rows = source.read('ContactServiceModel')[1] + [service(999999, 3, 999999, 8, 14)]
            rescued = pb.player_gear_references(ServiceSource(rows, source))
            self.assertIn('ContactService 999999', rescued['WeaponMod']['1005'])
            self.assertNotIn('ContactService 46', rescued['WeaponMod']['1005'])

    def test_other_loot_blueprint_and_crafting_routes_survive_blocked_services(self):
        with static_data.StaticData() as source:
            rows = source.read('ContactServiceModel')[1]
            # Compare against an otherwise identical catalog with cap flags disabled.
            uncapped = ServiceSource([dict(r, UpgradeReady='0') for r in rows], source)
            old = pb.player_gear_references(uncapped)
            kinds = {}
            current = pb.player_gear_references(source, source_kinds=kinds)
            blocked_refs = {'ContactService 46', 'ContactService 47'}
            rescued = {rid for rid, evidence in old['WeaponMod'].items()
                       if blocked_refs & set(evidence) and set(evidence) - blocked_refs}
            self.assertTrue(rescued)
            self.assertLessEqual(rescued, current['WeaponMod'].keys())
            self.assertTrue(all(kinds['WeaponMod'][rid] - {'service'} for rid in rescued))

    def test_saved_overrides_move_between_main_other_and_hidden_without_loss(self):
        with tempfile.TemporaryDirectory() as config, static_data.StaticData() as source:
            path = Path(config) / pb.FILE
            path.parent.mkdir(parents=True, exist_ok=True)
            doc = pb.empty()

            def location():
                path.write_bytes(pb.encode(doc))
                model = pb.catalog(config, static_data.DEFAULT_DB)
                self.assertIsNone(model['error'])
                self.assertEqual(pb.load(config), doc)
                return [p['id'] for p in model['pages'] for g in p['grids']
                        if g['table'] == 'WeaponMod' for r in g['rows'] if r['id'] == '1005']

            self.assertEqual(location(), [])
            for column, value, expected in [('Cost', '=99', ['other-weapon-overrides']),
                    ('ServiceOptionId', '1', ['weapon-mods']),
                    ('ServiceOptionId', '', ['other-weapon-overrides']), ('Cost', '', [])]:
                doc = pb.apply_edits(doc, {'cells': [{'table': 'WeaponMod', 'id': '1005',
                                      'column': column, 'value': value}]}, source)
                self.assertEqual(location(), expected)
                _, touched = pb.sql(doc, source)
                self.assertEqual(touched, {('WeaponMod', rid, col) for rid, fields in doc['tables'].get('WeaponMod', {}).items()
                                           for col in fields})


if __name__ == '__main__':
    unittest.main()
