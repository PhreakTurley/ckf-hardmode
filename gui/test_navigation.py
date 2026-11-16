"""Mod ownership, retained headings, and shared-weapon navigation policy."""
from collections import Counter
import copy
import sys
import unittest

import navigation
import serve
import player_balance
import static_data


class NavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.settings = serve.load_settings()
        cls.model = serve.App(cls.settings, 'test-token').api_model()
        cls.original = player_balance.catalog(serve.config_dir_for(cls.settings), cls.settings.get('officialDataPath'))

    def test_section_owners_follow_the_implementation_that_uses_them(self):
        expected = {'EnemyArmor': 'enemy-balance', 'SpawnWeights': 'hard-mode',
                    'LegacyEnemyData': 'hard-mode', 'PlayerRebalance': 'hard-mode',
                    'EnemyRebalance': 'hard-mode', 'General': 'hard-mode'}
        for section in self.model['sections']:
            for subsystem in section['subsystems']:
                self.assertEqual(section['owner'], 'player-balance' if subsystem.startswith('Talents') else expected.get(subsystem, 'hard-mode'))
        with self.assertRaisesRegex(ValueError, 'Split the mixed-mod'):
            navigation.section_owner({'id':'mixed', 'subsystems':['EnemyArmor', 'Fatigue']})

    def test_partition_preserves_every_record_and_its_metadata(self):
        def records(pages):
            return Counter((g.get('key'), g['table'], r['id'], repr(r))
                           for p in pages for g in p['grids'] for r in g['rows'])
        self.assertEqual(records(self.original['pages']), records(self.model['playerBalance']['pages']))
        self.assertEqual({p['title'] for p in self.original['pages']},
                         {p['title'] for p in self.model['playerBalance']['pages']})
        self.assertEqual(len({p['id'] for p in self.model['playerBalance']['pages']}),
                         len(self.model['playerBalance']['pages']))

    def test_enemy_rules_and_protected_hard_mode_rows_are_separated(self):
        pages = self.model['playerBalance']['pages']
        enemy = next(p for p in pages if p['id']=='enemy-balance-rules')
        self.assertEqual(enemy['owner'], 'enemy-balance')
        self.assertEqual({r['id'] for g in enemy['grids'] for r in g['rows']}, player_balance.ENEMY_RULES)
        for page in pages:
            for grid in page['grids']:
                for row in grid['rows']:
                    if row.get('owner'):
                        self.assertEqual(page['owner'], navigation.ROW_OWNERS[row['owner']])
        self.assertTrue(any(p['id']=='hard-mode-traits' for p in pages))

    def test_actual_shared_weapons_are_present_only_under_player_balance(self):
        with static_data.StaticData(self.settings.get('officialDataPath')) as source:
            enemy_ids={r['WeaponTypeId'] for r in source.read('MonsterTypeModel')[1]}
        weapon_pages=[p for p in self.model['playerBalance']['pages'] if any(g['table']=='Weapon' for g in p['grids'])]
        shared={r['id'] for p in weapon_pages for g in p['grids'] if g['table']=='Weapon' for r in g['rows']} & enemy_ids
        self.assertTrue(shared, 'The shared-weapon check needs actual overlap with enemy references.')
        self.assertTrue(all(p['owner']=='player-balance' for p in weapon_pages))

    def test_weapon_rows_cannot_be_routed_to_an_enemy_category(self):
        pages=[{'id':'weapon','title':'Weapons','group':'Weapons','grids':[
            {'table':'Weapon','columns':[],'rows':[{'id':'1','owner':'Enemy Balance'}]}]}]
        before=copy.deepcopy(pages)
        result=navigation.catalog_pages(pages)
        self.assertEqual(result[0]['owner'], 'player-balance')
        self.assertEqual(pages, before)


UI = r'''
setTimeout(function () {
  let passed=0;
  function ck(name,ok) {if (!ok) throw new Error(name);passed++;console.log('PASS '+name);}
  function owner(id) {return $('#index').find(n=>n.attrs['data-mod-owner']===id)[0];}
  const owners=$('#index').find(n=>!!n.attrs['data-mod-owner']);
  ck('each owning mod has one separate container', owners.length===MODEL.modOwners.length
    && MODEL.modOwners.every(o=>owners.filter(n=>n.attrs['data-mod-owner']===o.id).length===1));
  ck('owning mods are never nested inside each other', owners.every(o=>!o.find(n=>n!==o && !!n.attrs['data-mod-owner']).length));
  for (const section of MODEL.sections) {
    ck(section.title+' is under its owning mod', owner(section.owner).find(n=>n.attrs['data-section-id']===section.id).length===1);
  }
  for (const page of MODEL.playerBalance.pages) {
    ck(page.title+' catalog is under '+page.owner, owner(page.owner).find(n=>n.attrs['data-player-page']===page.id).length===1);
  }
  ck('Player Balance retains Talent Balance', owner('player-balance').find(n=>n.attrs['data-native-group']==='talent-balance').length===1);
  ck('Enemy Gear is preserved in both relevant mods', ['enemy-balance','hard-mode'].every(id=>owner(id).find(n=>n.attrs['data-native-group']==='enemy-gear').length===1));
  ck('Hard Mode retains Bundled Rebalances and Systems', ['bundled-rebalances','systems'].every(g=>owner('hard-mode').find(n=>n.attrs['data-native-group']===g).length===1));
  ck('shared weapons have no enemy sidebar entries', !owner('enemy-balance').find(n=>String(n.attrs['data-player-page'] || '').startsWith('weapon-')).length);
  const page=MODEL.playerBalance.pages.find(p=>p.owner==='player-balance' && p.id.startsWith('weapon-'));
  const link=owner('player-balance').find(n=>n.attrs['data-player-page']===page.id)[0];
  link.fire('click');
  ck('regrouped links still select their existing editing page', SEL==='pb:'+page.id && $('#panel').textContent.includes(page.title));
  owner('player-balance').open=false;owner('player-balance').fire('toggle');render();
  ck('mod folding survives a render', !owner('player-balance').open);
  owner('player-balance').open=true;owner('player-balance').fire('toggle');render();
  ck('mod can be reopened without changing the selected page', owner('player-balance').open && SEL==='pb:'+page.id);
  ck('navigation introduced no pending edits', dirtyPaths().length===0);
  console.log('Mod-owned sidebar: '+passed+' passed');process.exit(0);
},0);
'''

if __name__ == '__main__':
    if '--ui' in sys.argv:
        sys.exit(serve.selftest_dom(serve.App(serve.load_settings(),'test-token').api_model(), UI))
    unittest.main()
