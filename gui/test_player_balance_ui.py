"""Exercise the current Workshop UI with a real official-data model in Node."""
from pathlib import Path
import sys

import serve

config = Path(r'C:\Program Files (x86)\Steam\steamapps\common\Cyber Knights Flashpoint\BepInEx\config')
model = serve.App({'gameDir': '', 'configDirOverride': str(config), 'stripReadme': False}, 'test-token').api_model()
# Seed a stored override in the test model so clearing it exercises removal,
# independently of whichever cells the maintainer currently has adjusted.
laser = next(p for p in model['playerBalance']['pages'] if p['id'] == 'weapon-17')['grids'][0]
model['playerBalance']['document']['tables'].setdefault('Weapon', {}).setdefault(laser['rows'][0]['id'], {})[laser['columns'][0]['name']] = '=7'

ASSERTIONS = r'''
setTimeout(async function () {
  let passed = 0;
  function ck(name, ok) {if (!ok) throw new Error(name);passed++;console.log('PASS '+name);}
  ck('official catalogs loaded completely', MODEL.playerBalance.pages.length > 0 && !MODEL.playerBalance.error);
  const rules = MODEL.values.overlays['ckf.hardmode.d/RuleModel.csv'];
  ck('surprised accuracy is absent from the Hard Mode rule grid', !rules.rows.some(function(r) {return r.cells[0]==='22';}));
  ck('surprised accuracy has its Workshop owner', MODEL.playerBalance.pages.find(function(p) {return p.id==='rules';}).grids.some(function(g) {return g.rows.some(function(r) {return r.id==='22';});}));
  const panel = $('#panel');
  const find = function (fn) {return panel.find(fn);};
  const beforeBlueprintView = JSON.stringify(playerChanges());
  SEL='pb:weapon-3';render();
  function blueprintCell(table, id) {
    const row = find(n => n.tagName==='TR' && n.getAttribute('data-player-row')===table+' '+id)[0];
    return row && row.find(n => n.tagName==='TD' && n._cls().includes('pb-blueprint'))[0];
  }
  ck('weapon blueprint column is visible by default', find(n => n.tagName==='TH' && n.textContent==='Blueprint').length===1);
  ck('lootable weapon blueprint is labelled and cites its row', blueprintCell('Weapon','1008').textContent==='Blueprint'
     && blueprintCell('Weapon','1008').title.includes('Blueprint 101008'));
  ck('story-only weapon has a blank blueprint cell', blueprintCell('Weapon','1028').textContent==='');
  ck('blueprint marker has no editable input', !blueprintCell('Weapon','1008').find(n => n.tagName==='INPUT').length);
  const bpSort = find(n => n.tagName==='SELECT' && n.getAttribute('aria-label')==='Sort by AR · Weapon stats')[0];
  bpSort.value='blueprint';bpSort.fire('change');
  const bpDirection = find(n => n.tagName==='SELECT' && n.getAttribute('aria-label')==='Sort direction AR · Weapon stats')[0];
  bpDirection.value='descending';bpDirection.fire('change');
  const bpRows = find(n => n.tagName==='TR' && n.getAttribute('data-player-row'));
  let blankBlueprint = false, groupedBlueprints = true;
  for (const row of bpRows) {
    const cell = row.find(n => n.tagName==='TD' && n._cls().includes('pb-blueprint'))[0];
    if (!cell.textContent) blankBlueprint = true;
    else if (blankBlueprint) groupedBlueprints = false;
  }
  ck('blueprint descending sort places marked rows first', groupedBlueprints && blankBlueprint);
  const bpSearch=find(n => n.tagName==='INPUT' && n.getAttribute('type')==='search')[0];
  bpSearch.value='Blueprint';bpSearch.fire('input');
  ck('blueprint markers are searchable', find(n => n.tagName==='TD' && n._cls().includes('pb-blueprint')).length>0
     && find(n => n.tagName==='TD' && n._cls().includes('pb-blueprint')).every(n => n.textContent==='Blueprint'));
  const bpAll=find(n => n.tagName==='INPUT' && n.getAttribute('type')==='checkbox')[0];
  bpAll.checked=true;bpAll.fire('change');
  ck('show all columns retains exactly one blueprint column', find(n => n.tagName==='TH' && n.textContent==='Blueprint').length===1);
  SEL='pb:weapon-mods';render();
  const bpModSearch=find(n => n.tagName==='INPUT' && n.getAttribute('type')==='search')[0];
  bpModSearch.value='Melee Damage 3';bpModSearch.fire('input');
  ck('explicit blueprint loot marks a mod even when Lootable is zero', blueprintCell('WeaponMod','132').textContent==='Blueprint'
     && blueprintCell('WeaponMod','132').title.includes('MissionLoot 9130'));
  ck('blueprint view operations never create saved edits', JSON.stringify(playerChanges())===beforeBlueprintView);
  SEL='pb:weapon-16';render();
  const clawAll = find(function(n) {return n.tagName==='INPUT' && n.getAttribute('type')==='checkbox';})[0];
  clawAll.checked=true;clawAll.fire('change');
  ck('Claws attack range is absent even with all columns shown',
     !find(function(n) {return n.tagName==='INPUT' && /^Talent .*\.Range$/.test(n.getAttribute('data-player-target') || '');}).length);
  ck('uniform Claws attack fields remain available in advanced columns',
     find(function(n) {return n.tagName==='INPUT' && /^Talent .*\.ApCost$/.test(n.getAttribute('data-player-target') || '');}).length>0);
  SEL='pb:weapon-17';render();
  ck('eye laser weapon and attack fields share one grid', find(function (n) {return n.tagName==='TABLE';}).length===1
     && find(function(n) {return n.tagName==='TH' && n.textContent==='Attack';}).length===1);
  const input = find(function (n) {return n.tagName==='INPUT' && n.getAttribute('type')==='text';})[0];
  ck('a weapon stat can be edited', !!input);
  input.value='=0';input.fire('input');
  ck('explicit zero is red', input.parent._cls().includes('overlay-overwrite'));
  ck('an edit is included in the save payload', buildEdits().playerBalance.cells.some(function (c) {return c.value==='=0';}));
  input.value='';input.fire('input');
  ck('clearing an override remains an explicit edit', buildEdits().playerBalance.cells.some(function (c) {return c.value==='';}));
  ck('integer rounding agrees at positive and negative ties', playerRound(2.5)===2 && playerRound(3.5)===4 && playerRound(-2.5)===-2);
  const native = document.querySelector('#index');
  const drones = native.find(function(n) {return n.tagName==='DETAILS' && n.textContent.startsWith('Drone weapons');})[0];
  ck('drone weapon sections start collapsed', !drones.open);
  SEL='pb:weapon-1';render();
  const melee = MODEL.playerBalance.pages.find(function(p) {return p.id==='weapon-1';}).grids[0];
  const headers = find(function(n) {return n.tagName==='TH';});
  ck('PL rarity and cost follow name', headers.slice(0,4).map(function(n) {return n.textContent;}).join('|')==='Name|PL|Rarity|Cost');
  ck('icon references and separating headings are displayed', find(function(n) {return n._cls().includes('pb-icon');}).length > 0
     && find(function(n) {return n._cls().includes('pb-section');}).length > 1);
  ck('varying damage fields are grouped into attack modes', ['Damage 1','Damage 2'].every(function(group) {
    return headers.some(function(n) {return n.textContent===group;})===melee.columns.some(function(c) {return c.group===group;});
  }));
  ck('varying weapon effects are visible', headers.some(function(n) {return n.getAttribute('title')==='WeaponEffect';})
     ===melee.columns.some(function(c) {return c.name==='WeaponEffect';}));
  const widthGrid = {table:'WidthFixture',rows:[{id:'1',baseline:{value:'1'}},{id:'2',baseline:{value:'1234567890123'}}]};
  ck('column widths include longest heading and offscreen value', playerColumnWidth(widthGrid,{name:'value',label:'Value'})
     >playerColumnWidth({table:'WidthFixture',rows:[widthGrid.rows[0]]},{name:'value',label:'Value'})
     && playerColumnWidth(widthGrid,{name:'value',label:'An even longer title for this field'})>playerColumnWidth(widthGrid,{name:'value',label:'Value'}));
  SEL='pb:weapon-mods';render();
  const modCategories=find(function(n) {return n._cls().includes('pb-category');});
  ck('weapon mods have three separate categories', modCategories.map(function(n) {return n.getAttribute('data-mod-category');}).join('|')==='Weapon Mods|Crafted Intrinsic|Intrinsic');
  ck('weapon and slot subsections stay inside each category', modCategories.every(function(n) {
    return n.children.some(function(c) {return c.tagName==='DETAILS' && c._cls().includes('pb-subsection');});
  }));
  ck('each category retains icon groups and editable fields', modCategories.every(function(n) {
    return n.find(function(c) {return c._cls().includes('pb-section');}).length>0
      && n.find(function(c) {return c.tagName==='INPUT' && c.getAttribute('data-player-target');}).length>0;
  }));
  const modSearch=find(function(n) {return n.tagName==='INPUT' && n.getAttribute('type')==='search';})[0];
  modSearch.value='Crafted Intrinsic';modSearch.fire('input');
  ck('search can select the crafted category without mixing the others',
     find(function(n) {return n._cls().includes('pb-category');}).length===1
     && find(function(n) {return n._cls().includes('pb-category');})[0].getAttribute('data-mod-category')==='Crafted Intrinsic');
  ck('search opens matching category and its fitment subsections',
     find(function(n) {return n.tagName==='DETAILS' && n._cls().includes('pb-subsection');}).every(function(n) {return n.open;}));
  modSearch.value='';modSearch.fire('input');
  ck('weapon mods have editable stat cells', find(function(n) {return n.tagName==='INPUT' && n.getAttribute('type')==='text';}).length > 0);
  const modInput = find(function(n) {return n.tagName==='INPUT' && n.getAttribute('type')==='text';})[0];
  modInput.value='=19';modInput.fire('input');
  ck('weapon mod edits retain their table identity', buildEdits().playerBalance.cells.some(function(c) {return c.table==='WeaponMod' && c.value==='=19';}));
  SEL='pb:traits';render();
  ck('traits have score subsections', find(function(n) {return n.tagName==='SUMMARY' && n.textContent.startsWith('Trait score ');}).length>1);
  ck('trait effects display their owners', find(function(n) {return n._cls().includes('pb-section-name');}).length>0);
  ck('traits are paginated', find(function(n) {return n.tagName==='BUTTON' && n.textContent==='Next' && !n.disabled;}).length>0);
  const next = find(function(n) {return n.tagName==='BUTTON' && n.textContent==='Next' && !n.disabled;})[0];
  next.fire('click');
  ck('pagination advances', panel.textContent.includes('76–'));
  ck('pagination advances only its own grid', find(function(n) {return n.tagName==='SPAN' && n.textContent.startsWith('76–');}).length===1);
  const search = find(function(n) {return n.tagName==='INPUT' && n.getAttribute('type')==='search';})[0];
  search.value='Checked Out';search.fire('input');
  ck('fatigue rows are read-only in the Workshop trait catalog', find(function(n) {return n._cls().includes('readonly');}).length>0);
  SEL='pb:leverage';render();
  ck('leverage has data-backed subsets', ['Other leverage','Face leverage','0-token leverage','Matrix-only leverage','Favor-cost leverage'].every(function(title) {return panel.textContent.includes(title);}));
  const leverageSearch = find(function(n) {return n.tagName==='INPUT' && n.getAttribute('type')==='search';})[0];
  leverageSearch.value='Suppressed Alarm';leverageSearch.fire('input');
  ck('leverage has readable names', panel.textContent.includes('Suppressed Alarm'));
  const all = find(function(n) {return n.tagName==='INPUT' && n.getAttribute('type')==='checkbox';})[0];
  const count = find(function(n) {return n.tagName==='TH';}).length;
  all.checked=true;all.fire('change');
  ck('advanced columns can be revealed', find(function(n) {return n.tagName==='TH';}).length>count);
  SEL='pb:implant-global';render();
  ck('global cyberware settings omit irrelevant grid controls', !find(function(n) {return n.tagName==='INPUT' && n.getAttribute('type')==='search';}).length
     && find(function(n) {return n.tagName==='INPUT' && n.getAttribute('type')==='number';}).length===3);
  const pending = JSON.stringify(W.player);
  await $('#save').listeners.click[0]();
  ck('a refused save preserves pending edits', JSON.stringify(W.player) === pending && dirtyPaths().length > 0);
  console.log('Workshop UI: '+passed+' passed');process.exit(0);
}, 0);
'''

if __name__ == '__main__':
    sys.exit(serve.selftest_dom(model, ASSERTIONS))
