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

# Keep the visual-picker assertion independent of uniform shipped item models.
model['playerBalance']['document']['tables'].setdefault('Item', {}).setdefault('11', {})['Asset3DTypeId'] = '1001'

# Read-only view fixtures let the Node DOM test exercise asynchronous tag moves.
with serve.static_data.StaticData() as preview_source:
    preview_doc = serve.player_balance.apply_edits(model['playerBalance']['document'], {'cells': [
        {'table': 'Item', 'id': '9', 'column': 'ItemClass', 'value': '1'}]}, preview_source, config)
preview_catalog = serve.player_balance.catalog(config, serve.static_data.DEFAULT_DB, document=preview_doc)
assert not preview_catalog['error'], preview_catalog['error']
model['_consumablePreviews'] = {
    'original': [p for p in model['playerBalance']['pages'] if p['group'] == 'Consumables'],
    'moved': [p for p in preview_catalog['pages'] if p['group'] == 'Consumables'],
}

ASSERTIONS = r'''
setTimeout(async function () {
  let passed = 0;
  function ck(name, ok) {if (!ok) throw new Error(name);passed++;console.log('PASS '+name);}
  ck('official catalogs loaded completely', MODEL.playerBalance.pages.length > 0 && !MODEL.playerBalance.error);
  const rules = MODEL.values.overlays['ckf.hardmode.d/RuleModel.csv'];
  ck('surprised accuracy is absent from the Hard Mode rule grid', !rules.rows.some(function(r) {return r.cells[0]==='22';}));
  ck('surprised accuracy has its Workshop owner', MODEL.playerBalance.pages.find(function(p) {return p.id==='rules';}).grids.some(function(g) {return g.rows.some(function(r) {return r.id==='22';});}));
  const normalImplants=MODEL.playerBalance.pages.filter(p=>p.id.startsWith('implant-')).flatMap(p=>p.grids).filter(g=>g.table==='Implant').flatMap(g=>g.rows);
  const otherImplants=MODEL.playerBalance.pages.filter(p=>p.id==='other-cyberware-overrides').flatMap(p=>p.grids).flatMap(g=>g.rows);
  const normalConsumables=MODEL.playerBalance.pages.filter(p=>p.group==='Consumables' && p.id!=='other-consumable-overrides').flatMap(p=>p.grids).flatMap(g=>g.rows);
  const otherConsumables=MODEL.playerBalance.pages.filter(p=>p.id==='other-consumable-overrides').flatMap(p=>p.grids).flatMap(g=>g.rows);
  ck('normal consumable tables contain only items with positive acquisition references', normalConsumables.length>0 && normalConsumables.every(r=>r.acquisition.length));
  ck('unreachable consumable overrides are kept out of normal tables', otherConsumables.every(r=>!r.acquisition.length && !normalConsumables.some(n=>n.id===r.id)));
  ck('normal cyberware rows have positive acquisition references', normalImplants.length>0 && normalImplants.every(r=>r.acquisition && r.acquisition.length));
  ck('unreachable cyberware overrides stay separate from the normal catalog', otherImplants.every(r=>!r.acquisition.length
     && !normalImplants.some(n=>n.id===r.id)));
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
  const bpSort = find(n => n.tagName==='SELECT' && n.getAttribute('aria-label')==='Sort by Assault Rifle · Weapon stats')[0];
  ck('Cost is the selected default equipment sort', bpSort.value==='column:Cost');
  bpSort.value='blueprint';bpSort.fire('change');
  const bpDirection = find(n => n.tagName==='SELECT' && n.getAttribute('aria-label')==='Sort direction Assault Rifle · Weapon stats')[0];
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
  const beforeServiceView=JSON.stringify(playerChanges());
  let unchangedServices=true, assignedServices=0, noUnassigned=true;
  for (const page of MODEL.playerBalance.pages) for (const grid of page.grids) {
    if (!grid.blueprintColumn) continue;
    for (const row of grid.rows) {
      const original=playerServiceAssignment(playerCell(grid,row,{name:grid.serviceColumn.name}),grid.serviceColumn.options);
      const shown=playerService(grid,row);
      if (grid.serviceColumn.source!=='cyberware' && Object.prototype.hasOwnProperty.call(grid.serviceColumn.options,original.id) && original.attainable!==false) {
        assignedServices++;
        if (JSON.stringify(original)!==JSON.stringify(shown)) unchangedServices=false;
      }
      if (shown.label==='Unassigned') noUnassigned=false;
    }
  }
  ck('all attainable weapon and mod service declarations remain unchanged', assignedServices>0 && unchangedServices);
  ck('weapon and mod service cells never declare Unassigned', noUnassigned);
  SEL='pb:weapon-3';render();
  const sourceSearch=find(n=>n.tagName==='INPUT' && n.getAttribute('type')==='search')[0];
  sourceSearch.value='Whaler';sourceSearch.fire('input');
  function whalerServiceCell() {
    const row=find(n=>n.tagName==='TR' && n.getAttribute('data-player-row')==='Weapon 1028')[0];
    return row && row.find(n=>n.tagName==='TD' && n._cls().includes('pb-service'))[0];
  }
  ck('story equipment shows Mission in Service', whalerServiceCell().textContent==='Mission');
  const sourceAll=find(n=>n.tagName==='INPUT' && n.getAttribute('type')==='checkbox')[0];
  sourceAll.checked=true;sourceAll.fire('change');
  const sourceInput=find(n=>n.tagName==='INPUT' && n.getAttribute('data-player-target')==='Weapon 1028.ServiceOptionId')[0];
  const previousServiceValue=sourceInput.value;
  sourceInput.value='1';sourceInput.fire('input');
  const arGrid=MODEL.playerBalance.pages.find(p=>p.id==='weapon-3').grids[0];
  ck('a pending real service assignment takes precedence immediately', whalerServiceCell().textContent===arGrid.serviceColumn.options['1'].label);
  sourceInput.value=previousServiceValue;sourceInput.fire('input');
  ck('clearing the pending service edit restores Mission', whalerServiceCell().textContent==='Mission');
  ck('availability display never creates saved edits', JSON.stringify(playerChanges())===beforeServiceView);
  const sourceGrid={table:'ServiceFixture',serviceColumn:{name:'Option',options:{'1':{label:'Shop',detail:'original service'}}}};
  const sourceRow={id:'1',baseline:{Option:'-1'},serviceFallback:{label:'Loot / Blueprint',detail:'sources'}};
  ck('unassigned service uses combined availability', playerService(sourceGrid,sourceRow).label==='Loot / Blueprint');
  sourceRow.baseline.Option='1';
  ck('matched service details are preserved as well as its label', playerService(sourceGrid,sourceRow).detail==='original service');
  sourceRow.baseline.Option='999';
  ck('unresolved positive service assignments retain their declaration', playerService(sourceGrid,sourceRow).label==='Unresolved service 999');
  sourceRow.baseline.Option='-1';delete sourceRow.serviceFallback;
  ck('other catalog service behavior remains unchanged', playerService(sourceGrid,sourceRow).label==='Unassigned');
  const cappedPlayer=JSON.stringify(W.player);
  SEL='pb:weapon-mods';render();
  const cappedGrid=MODEL.playerBalance.pages.find(p=>p.id==='weapon-mods').grids.find(g=>g.rows.some(r=>
    g.serviceColumn.options[r.baseline.ServiceOptionId] && g.serviceColumn.options[r.baseline.ServiceOptionId].attainable===false));
  const cappedRow=cappedGrid.rows.find(r=>cappedGrid.serviceColumn.options[r.baseline.ServiceOptionId]
    && cappedGrid.serviceColumn.options[r.baseline.ServiceOptionId].attainable===false);
  const cappedRecords=W.player.tables.WeaponMod || (W.player.tables.WeaponMod={});
  const cappedRecord=cappedRecords[cappedRow.id] || (cappedRecords[cappedRow.id]={});
  delete cappedRecord.ServiceOptionId;
  const cappedSearch=find(n=>n.tagName==='INPUT' && n.getAttribute('type')==='search')[0];
  cappedSearch.value=cappedRow.name;cappedSearch.fire('input');
  const cappedCell=()=>find(n=>n.tagName==='TR' && n.getAttribute('data-player-row')==='WeaponMod '+cappedRow.id)[0]
    .find(n=>n.tagName==='TD' && n._cls().includes('pb-service'))[0];
  ck('otherwise obtainable gear uses availability instead of a capped service', cappedCell().textContent===cappedRow.serviceFallback.label && !cappedCell().textContent.includes('Imported Weapon Mods'));
  ck('unattainable service tooltip cites its cap marker', cappedCell().title.includes('UpgradeReady=2') && cappedCell().title.includes('exceeds cap'));
  const cappedAll=find(n=>n.tagName==='INPUT' && n.getAttribute('type')==='checkbox')[0];
  cappedAll.checked=true;cappedAll.fire('change');
  const cappedInput=find(n=>n.tagName==='INPUT' && n.getAttribute('data-player-target')==='WeaponMod '+cappedRow.id+'.ServiceOptionId')[0];
  cappedInput.value='1';cappedInput.fire('input');
  ck('pending attainable assignment clears the unattainable marker', !cappedCell().textContent.includes('Unattainable')
     && cappedCell().textContent===cappedGrid.serviceColumn.options['1'].label);
  cappedInput.value='';cappedInput.fire('input');
  ck('reset restores availability instead of a capped service', cappedCell().textContent===cappedRow.serviceFallback.label);
  W.player=JSON.parse(cappedPlayer);
  SEL='pb:weapon-16';render();
  const clawAll = find(function(n) {return n.tagName==='INPUT' && n.getAttribute('type')==='checkbox';})[0];
  clawAll.checked=true;clawAll.fire('change');
  ck('Claws attack range is absent even with all columns shown',
     !find(function(n) {return n.tagName==='INPUT' && /^Talent .*\.Range$/.test(n.getAttribute('data-player-target') || '');}).length);
  ck('uniform Claws attack fields remain available in advanced columns',
     find(function(n) {return n.tagName==='INPUT' && /^Talent .*\.ApCost$/.test(n.getAttribute('data-player-target') || '');}).length>0);
  ck('Claws keeps one regular Service column with all columns shown', find(n=>n.tagName==='TH' && n.textContent==='Service').length===1
     && !find(n=>n.tagName==='TH' && n.textContent==='Cyberware Service').length);
  SEL='pb:weapon-17';render();
  ck('eye laser weapon and attack fields share one grid', find(function (n) {return n.tagName==='TABLE';}).length===1
     && find(function(n) {return n.tagName==='TH' && n.textContent==='Attack';}).length===1);
  const laserNames=MODEL.playerBalance.pages.find(p=>p.id==='weapon-17').grids[0];
  const brightshot=laserNames.rows.find(r=>r.id==='25001');
  ck('cyberweapon rows show the linked implant tier name', brightshot.name==='Brightshot Optic 2'
     && find(n=>n.tagName==='TR' && n.getAttribute('data-player-row')==='Weapon 25001')[0].textContent.includes('Brightshot Optic 2'));
  const cyberLabels=playerService(laserNames,brightshot);
  const expectedCyberLabels=Array.from(new Set(brightshot.cyberwareServices.map(ref=>
    playerServiceAssignment(playerCell({table:'Implant'},{id:ref.id,baseline:{ServiceOptionId:ref.baseline}},{name:'ServiceOptionId'}),
      laserNames.serviceColumn.options).label))).join('; ');
  ck('regular Service shows cyberware service names and keeps source ids in the tooltip', cyberLabels.label===expectedCyberLabels
     && !cyberLabels.label.includes('(option ') && cyberLabels.detail.includes('Implant '+brightshot.cyberwareServices[0].id+'.ServiceOptionId'));
  const brightshotCell=()=>find(n=>n.tagName==='TR' && n.getAttribute('data-player-row')==='Weapon 25001')[0]
    .find(n=>n.tagName==='TD' && n._cls().includes('pb-service'));
  ck('Eye Lasers has only the regular Service column', find(n=>n.tagName==='TH' && n.textContent==='Service').length===1
     && !find(n=>n.tagName==='TH' && n.textContent==='Cyberware Service').length
     && brightshotCell().length===1 && brightshotCell()[0].textContent===expectedCyberLabels);
  const serviceSnapshot=JSON.stringify(W.player), linkedImplant=brightshot.cyberwareServices[0];
  const nextService=Object.keys(laserNames.serviceColumn.options).find(id=>laserNames.serviceColumn.options[id].attainable
    && laserNames.serviceColumn.options[id].label!==cyberLabels.label);
  const implantEdits=W.player.tables.Implant || (W.player.tables.Implant={});
  (implantEdits[linkedImplant.id] || (implantEdits[linkedImplant.id]={})).ServiceOptionId=nextService;
  render();
  const nextServiceName=laserNames.serviceColumn.options[nextService].label;
  ck('pending implant service edits update the regular column and Service sort value', brightshotCell()[0].textContent===nextServiceName
     && playerSortValue(laserNames,brightshot,'service')===nextServiceName);
  const implantServiceSearch=find(n=>n.tagName==='INPUT' && n.getAttribute('type')==='search')[0];
  implantServiceSearch.value=nextServiceName;implantServiceSearch.fire('input');
  ck('service search finds cyberweapons by their linked implant service', brightshotCell().length===1);
  ck('the consolidated display retains the native implant service save target', buildEdits().playerBalance.cells.some(c=>
    c.table==='Implant' && c.id===linkedImplant.id && c.column==='ServiceOptionId' && c.value===nextService));
  W.player=JSON.parse(serviceSnapshot);render();
  const priceSnapshot=JSON.stringify(W.player), priceTarget=brightshot.targets.Cost;
  const priceColumn=laserNames.columns.concat(laserNames.advanced).find(c=>c.name==='Cost');
  W.player.implantMultipliers.Cost=2;
  const priceImplants=W.player.tables.Implant || (W.player.tables.Implant={});
  (priceImplants[priceTarget.id] || (priceImplants[priceTarget.id]={})).Cost='+50';
  const priceWeapons=W.player.tables.Weapon || (W.player.tables.Weapon={});
  (priceWeapons[brightshot.id] || (priceWeapons[brightshot.id]={})).Cost='999999';
  render();
  const priceInput=()=>find(n=>n.tagName==='INPUT' && n.getAttribute('data-player-target')==='Implant '+priceTarget.id+'.Cost')[0];
  ck('cyberweapon Cost binds to the linked implant and includes its Price multiplier', !!priceInput()
     && brightshot.baseline.Cost==='250' && priceInput().value==='+50' && String(priceInput().placeholder)==='500'
     && playerCell(laserNames,brightshot,priceColumn).target.table==='Implant'
     && playerEffectiveColumnValue(laserNames,brightshot,priceColumn)===600);
  ck('Cost sorting uses implant price instead of the legacy weapon price', playerSortValue(laserNames,brightshot,'column:Cost')===600);
  const displayedPrices=find(n=>n.tagName==='TR' && n.getAttribute('data-player-row')).map(n=>{
    const id=n.getAttribute('data-player-row').split(' ')[1];
    return playerEffectiveColumnValue(laserNames,laserNames.rows.find(r=>r.id===id),priceColumn);
  });
  ck('default rows are ordered by current implant prices', displayedPrices.every((v,i)=>i===0 || v>=displayedPrices[i-1]));
  priceInput().value='=7';priceInput().fire('input');
  ck('editing cyberweapon Cost saves to the native implant without replacing a weapon override', buildEdits().playerBalance.cells.some(c=>
     c.table==='Implant' && c.id===priceTarget.id && c.column==='Cost' && c.value==='=7')
     && W.player.tables.Weapon[brightshot.id].Cost==='999999' && playerSortValue(laserNames,brightshot,'column:Cost')===14);
  priceInput().value='';priceInput().fire('input');
  ck('clearing the implant price override restores its baseline times the Price multiplier', playerSortValue(laserNames,brightshot,'column:Cost')===500);
  W.player=JSON.parse(priceSnapshot);render();

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
  const visualAll=find(n=>n.tagName==='INPUT' && n.getAttribute('type')==='checkbox')[0];
  visualAll.checked=true;visualAll.fire('change');
  const modGrid=MODEL.playerBalance.pages.find(p => p.id==='weapon-mods').grids.find(g => g.iconEditor);
  const modRow=modGrid.rows[0], modEditor=modGrid.iconEditor;
  const originalVisual=(((W.player.tables || {}).WeaponMod || {})[modRow.id] || {})[modEditor.column];
  const baseVisual=String(modRow.baseline[modEditor.column]);
  const newVisual=modEditor.choices.find(c => c.thumbnail!==modEditor.assets[baseVisual].thumbnail);
  const modPicker=() => find(n => n.tagName==='SELECT' && n.getAttribute('aria-label')===modRow.name+' visual')[0];
  ck('multi-graphic mods have visual dropdowns without duplicate numeric controls', !!modPicker()
     && !find(n => n.tagName==='INPUT' && n.getAttribute('data-player-target')==='WeaponMod '+modRow.id+'.Asset3DTypeId').length);
  ck('unchanged visuals use the same short label as manual choices', modPicker().children[0].textContent===modEditor.assets[baseVisual].label
     && !modPicker().parent.find(n=>n.tagName==='SMALL').length);
  modPicker().value=newVisual.id;modPicker().fire('change');
  ck('changing a mod visual immediately moves its icon group', modRow.sectionKey===newVisual.thumbnail
     && modRow.icon===newVisual.name && modPicker().value===newVisual.id);
  const visualRow=find(n => n.tagName==='TR' && n.getAttribute('data-player-row')==='WeaponMod '+modRow.id)[0];
  const sectionRows=visualRow.parent.children;
  let visualHeading=null;
  for (const r of sectionRows) {if (r===visualRow) break;if (r._cls().includes('pb-section')) visualHeading=r;}
  ck('moved mod appears beneath the selected visual heading', visualHeading && visualHeading.textContent.includes(newVisual.name));
  ck('visual change preserves the native mod save identity', buildEdits().playerBalance.cells.some(c =>
     c.table==='WeaponMod' && c.id===modRow.id && c.column==='Asset3DTypeId' && c.value===newVisual.id));
  modPicker().value='';modPicker().fire('change');
  ck('default restores the official mod visual and group', modRow.sectionKey===modEditor.assets[baseVisual].thumbnail
     && modPicker().value==='');
  if (originalVisual!==undefined) W.player.tables.WeaponMod[modRow.id][modEditor.column]=originalVisual;
  const iconPlayer=JSON.stringify(W.player);
  const modPage=MODEL.playerBalance.pages.find(p=>p.id==='weapon-mods'), originalModGrids=modPage.grids;
  const iconFixture=JSON.parse(JSON.stringify(originalModGrids.find(g=>g.iconEditor && new Set(g.rows.map(r=>r.baseline.Asset3DTypeId)).size>1)));
  const firstIconRow=iconFixture.rows[0];
  const secondIconRow=iconFixture.rows.find(r=>iconFixture.iconEditor.assets[r.baseline.Asset3DTypeId].thumbnail
    !==iconFixture.iconEditor.assets[firstIconRow.baseline.Asset3DTypeId].thumbnail);
  iconFixture.rows=[firstIconRow,secondIconRow];
  for (const row of iconFixture.rows) {
    const fields=(W.player.tables.WeaponMod || {})[row.id];if(fields) delete fields.Asset3DTypeId;
  }
  modPage.grids=[iconFixture];render();
  const fixturePicker=()=>find(n=>n.tagName==='SELECT' && n.getAttribute('aria-label')===firstIconRow.name+' visual')[0];
  ck('different current graphics keep the visual column visible', !!fixturePicker());
  fixturePicker().value=String(secondIconRow.baseline.Asset3DTypeId);fixturePicker().fire('change');
  ck('making every graphic identical automatically hides the visual column', !fixturePicker()
     && !find(n=>n.tagName==='TH' && n.textContent==='Visual').length);
  ck('hidden visual changes remain in the native save payload', buildEdits().playerBalance.cells.some(c=>
     c.table==='WeaponMod' && c.id===firstIconRow.id && c.column==='Asset3DTypeId'
     && c.value===String(secondIconRow.baseline.Asset3DTypeId)));
  const uniformAll=find(n=>n.tagName==='INPUT' && n.getAttribute('type')==='checkbox')[0];
  uniformAll.checked=true;uniformAll.fire('change');
  ck('Show all reveals uniform visual pickers for editing', !!fixturePicker());
  fixturePicker().value='';fixturePicker().fire('change');
  uniformAll.checked=false;uniformAll.fire('change');
  ck('restoring different graphics makes the visual column visible again', !!fixturePicker());
  W.player=JSON.parse(iconPlayer);modPage.grids=originalModGrids;
  SEL='pb:weapon-12';render();
  const urbanGrid=MODEL.playerBalance.pages.find(p => p.id==='weapon-12').grids[0];
  ck('Urban Assault exposes the weapon icon picker', find(n => n.tagName==='H2' && n.textContent==='Urban Assault').length===1
     && find(n => n.tagName==='SELECT' && n.getAttribute('aria-label')===urbanGrid.rows[0].name+' icon / model').length===1);
  const savedPlayer=JSON.stringify(W.player);
  const fixtureCol={name:'Cost',label:'Cost',order:0,integer:true,visibilityPolicy:'varying'};
  const fixture={table:'VisibilityFixture',dynamicColumns:true,columns:[fixtureCol],advanced:[],
    rows:[{id:'1',name:'First',baseline:{Cost:'10'}},{id:'2',name:'Second',baseline:{Cost:'20'}}]};
  ck('a varying column starts visible', playerDisplayColumns(fixture,false).length===1);
  W.player.tables.VisibilityFixture={'1':{Cost:'=20'}};
  ck('equal effective values hide an overridden column', playerDisplayColumns(fixture,false).length===0);
  ck('Show all retains hidden overrides', playerDisplayColumns(fixture,true).length===1
     && playerCell(fixture,fixture.rows[0],fixtureCol).value==='20');
  W.player.tables.VisibilityFixture['1'].Cost='x0';W.player.tables.VisibilityFixture['2']={Cost:'x0'};
  ck('multiplication can collapse a column to zero', playerDisplayColumns(fixture,false).length===0);
  W.player.tables.VisibilityFixture['1'].Cost='invalid';
  ck('invalid edits stay visible for correction', playerDisplayColumns(fixture,false).length===1);
  W.player.tables.VisibilityFixture={};
  ck('clearing overrides restores varying columns', playerDisplayColumns(fixture,false).length===1);
  fixtureCol.integer=false;fixture.rows[0].baseline.Cost='1.1';fixture.rows[1].baseline.Cost='1.2';
  ck('different fractional values are not rounded into uniformity', playerDisplayColumns(fixture,false).length===1);
  fixture.rows=fixture.rows.slice(0,1);W.player.tables.VisibilityFixture['1']={Cost:'=3'};
  ck('single-row overrides remain editable', playerDisplayColumns(fixture,false).length===1);
  W.player=JSON.parse(savedPlayer);
  // Exercise blur/Enter repainting with two actual weapon records in the DOM.
  const originalUrbanGrids=MODEL.playerBalance.pages.find(p => p.id==='weapon-12').grids;
  const editGrid=JSON.parse(JSON.stringify(urbanGrid));
  editGrid.rows=editGrid.rows.slice(0,2);editGrid.columns=[fixtureCol];editGrid.advanced=[];
  editGrid.rows[0].baseline.Cost='10';editGrid.rows[1].baseline.Cost='20';
  for (const row of editGrid.rows) {
    const record=(W.player.tables.Weapon || {})[row.id];if (record) delete record.Cost;
  }
  MODEL.playerBalance.pages.find(p => p.id==='weapon-12').grids=[editGrid];render();
  const costInput=() => find(n => n.tagName==='INPUT' && n.getAttribute('data-player-target')==='Weapon '+editGrid.rows[0].id+'.Cost')[0];
  costInput().value='=20';costInput().fire('input');
  ck('a column stays present while typing', !!costInput());
  costInput().fire('change');await new Promise(resolve => setTimeout(resolve,0));
  ck('finishing an edit automatically hides the now uniform column', !costInput());
  ck('hidden column edits remain in the save payload', buildEdits().playerBalance.cells.some(c =>
     c.table==='Weapon' && c.id===editGrid.rows[0].id && c.column==='Cost' && c.value==='=20'));
  const editAll=find(n => n.tagName==='INPUT' && n.getAttribute('type')==='checkbox')[0];
  editAll.checked=true;editAll.fire('change');
  ck('Show all exposes the hidden edited column', costInput() && costInput().value==='20');
  costInput().value='';costInput().fire('input');costInput().fire('change');
  editAll.checked=false;editAll.fire('change');
  ck('clearing the hidden override restores default visibility', !!costInput());
  W.player=JSON.parse(savedPlayer);
  MODEL.playerBalance.pages.find(p => p.id==='weapon-12').grids=originalUrbanGrids;
  const implantPages=MODEL.playerBalance.pages.filter(p=>p.id.startsWith('implant-'));
  const fallbackSnapshot=JSON.stringify(W.player), cyberSearchPage=implantPages.find(p=>p.grids.some(g=>g.rows.some(r=>r.id==='904')));
  SEL='pb:'+cyberSearchPage.id;render();
  const fallbackGrid=cyberSearchPage.grids.find(g=>g.rows.some(r=>r.id==='904'));
  const fallbackRow=fallbackGrid.rows.find(r=>r.id==='904');
  const nativeImplants=W.player.tables.Implant || (W.player.tables.Implant={});
  const fallbackRecord=nativeImplants[fallbackRow.id] || (nativeImplants[fallbackRow.id]={});
  delete fallbackRecord.ServiceOptionId;render();
  const fallbackCell=()=>find(n=>n.tagName==='TR' && n.getAttribute('data-player-row')==='Implant '+fallbackRow.id)[0]
    .find(n=>n.tagName==='TD' && n._cls().includes('pb-service'))[0];
  ck('cyberware with both eligibility sources shows Starting Gear / Mission', fallbackCell().textContent==='Starting Gear / Mission');
  ck('Starting Gear and Mission remain independently identifiable', normalImplants.some(r=>r.serviceFallback.label==='Starting Gear')
     && normalImplants.some(r=>r.serviceFallback.label==='Mission'));
  const fallbackAll=find(n=>n.tagName==='INPUT' && n.getAttribute('type')==='checkbox')[0];
  fallbackAll.checked=true;fallbackAll.fire('change');
  const fallbackInput=find(n=>n.tagName==='INPUT' && n.getAttribute('data-player-target')==='Implant 904.ServiceOptionId')[0];
  fallbackInput.value='1';fallbackInput.fire('input');
  ck('an attainable cyberware service takes precedence over source labels', fallbackCell().textContent===fallbackGrid.serviceColumn.options['1'].label);
  fallbackInput.value='999999';fallbackInput.fire('input');
  ck('an unknown positive cyberware assignment falls back to eligibility', fallbackCell().textContent==='Starting Gear / Mission');
  fallbackInput.value='invalid';fallbackInput.fire('input');
  ck('invalid cyberware assignments remain visible for correction', fallbackCell().textContent==='Invalid service assignment');
  fallbackInput.value='';fallbackInput.fire('input');
  ck('clearing the service adjustment restores source labels immediately', fallbackCell().textContent==='Starting Gear / Mission');
  const blockedFixture={table:'Implant',serviceColumn:{name:'ServiceOptionId',fallbackUnavailable:true,
    options:{'2':{label:'',attainable:false,detail:'Beyond cap'}}}};
  ck('above-cap cyberware services also use source labels', playerService(blockedFixture,{id:'fixture',baseline:{ServiceOptionId:'2'},
    serviceFallback:{label:'Mission',detail:'Story evidence'}}).label==='Mission');
  W.player=JSON.parse(fallbackSnapshot);
  SEL='pb:weapon-17';render();
  const fallbackLaser=MODEL.playerBalance.pages.find(p=>p.id==='weapon-17').grids[0];
  const fallbackTrident=fallbackLaser.rows.find(r=>r.id==='25016');
  ck('cyberweapon service references use the same implant availability labels', playerService(fallbackLaser,fallbackTrident).label==='Mission');
  const consumableSnapshot=JSON.stringify(W.player), originalPlayerPages=MODEL.playerBalance.pages, originalApi=api;
  const itemNine=MODEL.playerBalance.pages.filter(p=>p.group==='Consumables').flatMap(p=>p.grids).flatMap(g=>g.rows).find(r=>r.id==='9');
  let previewFailure=false;
  api=async function(path,body) {
    if(path!=='/api/player-preview') return originalApi(path,body);
    if(previewFailure) return {ok:false,error:'Fixture view update refused'};
    const moved=body.playerBalance.cells.some(c=>c.table==='Item' && c.id==='9' && c.column==='ItemClass' && c.value==='1');
    return {ok:true,pages:JSON.parse(JSON.stringify(MODEL._consumablePreviews[moved ? 'moved' : 'original']))};
  };
  SEL='pb:consumable-4';render();
  const itemSelector=(suffix)=>find(n=>n.tagName==='SELECT' && n.getAttribute('aria-label')===itemNine.name+' '+suffix)[0];
  ck('consumables expose a category selector and linked talent icon and item model', !!itemSelector('tag') && !!itemSelector('talent icon') && !!itemSelector('item model'));
  const pendingItemCost=find(n=>n.tagName==='INPUT' && n.getAttribute('data-player-target')==='Item 9.Cost')[0];
  pendingItemCost.value='17';pendingItemCost.fire('input');
  itemSelector('tag').value='1';itemSelector('tag').fire('change');await PLAYER_PREVIEW_STATE.promise;
  ck('changing a consumable tag immediately moves it to the new section', SEL==='pb:consumable-1'
    && find(n=>n.tagName==='TR' && n.getAttribute('data-player-row')==='Item 9').length===1);
  ck('a tag move preserves pending native item stat edits', W.player.tables.Item['9'].Cost==='17'
    && buildEdits().playerBalance.cells.some(c=>c.table==='Item' && c.id==='9' && c.column==='ItemClass' && c.value==='1'));
  ck('Medical and Combat Drug menus do not mix in grenade icons or models', !itemSelector('talent icon').children.some(n=>n.value==='talent_item_grenade')
    && !itemSelector('item model').children.some(n=>['25','26'].includes(n.value)));
  itemSelector('talent icon').value='talent_item_bandage';itemSelector('talent icon').fire('change');await PLAYER_PREVIEW_STATE.promise;
  ck('talent icon edits keep a literal value and the linked native talent id', buildEdits().playerBalance.cells.some(c=>
    c.table==='Talent' && c.id==='75014' && c.column==='IconPng' && c.value==='talent_item_bandage'));
  itemSelector('item model').value='1001';itemSelector('item model').fire('change');await PLAYER_PREVIEW_STATE.promise;
  ck('item model edits retain their native item address', buildEdits().playerBalance.cells.some(c=>
    c.table==='Item' && c.id==='9' && c.column==='Asset3DTypeId' && c.value==='1001'));
  itemSelector('tag').value='';itemSelector('tag').fire('change');await PLAYER_PREVIEW_STATE.promise;
  ck('resetting a tag returns the item without discarding its other edits', SEL==='pb:consumable-4'
    && W.player.tables.Item['9'].Cost==='17' && W.player.tables.Talent['75014'].IconPng==='talent_item_bandage'
    && itemSelector('item model').value==='1001');
  previewFailure=true;itemSelector('tag').value='1';itemSelector('tag').fire('change');await PLAYER_PREVIEW_STATE.promise;
  ck('a refused view update preserves the pending tag and gives a retry', W.player.tables.Item['9'].ItemClass==='1'
    && panel.textContent.includes('Fixture view update refused') && find(n=>n.tagName==='BUTTON' && n.textContent==='Retry view update').length===1);
  previewFailure=false;find(n=>n.tagName==='BUTTON' && n.textContent==='Retry view update')[0].fire('click');await PLAYER_PREVIEW_STATE.promise;
  ck('retry rebuilds the correct destination without losing pending edits', SEL==='pb:consumable-1' && itemSelector('talent icon').value==='talent_item_bandage');
  SEL='pb:consumable-2';render();
  const grenadeGrid=MODEL.playerBalance.pages.find(p=>p.id==='consumable-2').grids[0], grenadeRow=grenadeGrid.rows.find(r=>r.id==='3');
  const grenadeAsset=find(n=>n.tagName==='SELECT' && n.getAttribute('aria-label')===grenadeRow.name+' talent asset')[0];
  ck('grenade talents expose a separate asset picker with grenade models', !!grenadeAsset
    && grenadeAsset.children.some(n=>n.value==='25') && !grenadeAsset.children.some(n=>n.value==='1001'));
  grenadeAsset.value='25';grenadeAsset.fire('change');await PLAYER_PREVIEW_STATE.promise;
  ck('extra talent assets save separately from inventory models', buildEdits().playerBalance.cells.some(c=>
    c.table==='Talent' && c.id==='75000' && c.column==='ExtraAsset' && c.value==='25'));
  SEL='pb:consumable-1';render();
  const medicalGrid=MODEL.playerBalance.pages.find(p=>p.id==='consumable-1').grids[0];
  const cloud=medicalGrid.rows.find(r=>r.id==='27');
  ck('consumables show a read-only Blueprint column with native source details', blueprintCell('Item','27').textContent==='Blueprint'
     && blueprintCell('Item','27').title.includes('Blueprint 27') && !blueprintCell('Item','27').find(n=>n.tagName==='INPUT').length);
  ck('nonpositive consumable services use loot and blueprint availability', playerService(medicalGrid,cloud).label==='Loot / Blueprint');
  const itemServiceSnapshot=JSON.stringify(W.player);
  W.player.tables.Item['27']={...(W.player.tables.Item['27'] || {}),ServiceOptionId:'999999'};
  ck('unknown consumable services fall back to availability', playerService(medicalGrid,cloud).label==='Loot / Blueprint');
  const cappedItemGrid={...medicalGrid,serviceColumn:{...medicalGrid.serviceColumn,options:{'999999':{label:'Hidden shop',attainable:false,detail:'Beyond cap'}}}};
  ck('capped consumable services are suppressed in favor of other sources', playerService(cappedItemGrid,cloud).label==='Loot / Blueprint');
  const realItemService=Object.keys(medicalGrid.serviceColumn.options).find(k=>Number(k)>0 && medicalGrid.serviceColumn.options[k].attainable!==false);
  W.player.tables.Item['27'].ServiceOptionId=realItemService;
  ck('attainable consumable service names take precedence', playerService(medicalGrid,cloud).label===medicalGrid.serviceColumn.options[realItemService].label);
  W.player=JSON.parse(itemServiceSnapshot);
  SEL='pb:consumable-4';render();
  const chemsGrid=MODEL.playerBalance.pages.find(p=>p.id==='consumable-4').grids[0];
  const storyItem=chemsGrid.rows.find(r=>r.id==='1100');
  ck('explicit story consumables show Mission without inventing loot or blueprint availability', playerService(chemsGrid,storyItem).label==='Mission'
     && !playerBlueprint(chemsGrid,storyItem).label);
  const visualPlayerSnapshot=JSON.stringify(W.player);
  const consumableVisualRow=chemsGrid.rows.find(r=>r.consumable.talent);
  const visualSelector=suffix=>find(n=>n.tagName==='SELECT' && n.getAttribute('aria-label')===consumableVisualRow.name+' '+suffix)[0];
  for (const row of chemsGrid.rows) {
    const item=W.player.tables.Item[row.id] || (W.player.tables.Item[row.id]={});item.Asset3DTypeId='1001';
    const talent=row.consumable.talent;if(!talent) continue;
    const fields=W.player.tables.Talent[talent.id] || (W.player.tables.Talent[talent.id]={});
    fields.IconPng='talent_item_bandage';fields.ExtraAsset='0';
  }
  render();
  ck('uniform consumable icons and both model assignments hide automatically after edits', !visualSelector('talent icon') && !visualSelector('item model')
     && !visualSelector('talent asset'));
  ck('hidden consumable visuals keep their native pending edits', buildEdits().playerBalance.cells.some(c=>
     c.table==='Talent' && c.id===consumableVisualRow.consumable.talent.id && c.column==='IconPng' && c.value==='talent_item_bandage'));
  const consumableAll=find(n=>n.tagName==='INPUT' && n.getAttribute('type')==='checkbox')[0];
  consumableAll.checked=true;consumableAll.fire('change');
  ck('Show all exposes uniform consumable visuals for further editing', !!visualSelector('talent icon') && !!visualSelector('item model') && !!visualSelector('talent asset'));
  W.player.tables.Item[consumableVisualRow.id].Asset3DTypeId='1002';W.player.tables.Talent[consumableVisualRow.consumable.talent.id].IconPng='combatdrug10';
  consumableAll.checked=false;consumableAll.fire('change');
  ck('different pending consumable visuals make the columns visible again', !!visualSelector('talent icon') && !!visualSelector('item model') && !visualSelector('talent asset'));
  W.player=JSON.parse(visualPlayerSnapshot);
  SEL='pb:consumable-6';render();
  ck('a uniform no-talent consumable table hides empty icons and repeated models', !find(n=>n.tagName==='TH' && ['Talent icon','Item model','Talent asset'].includes(n.textContent)).length);
  ck('consumable display changes do not create blueprint overrides', !buildEdits().playerBalance.cells.some(c=>c.column==='Blueprint'));
  W.player=JSON.parse(consumableSnapshot);MODEL.playerBalance.pages=originalPlayerPages;api=originalApi;PLAYER_PREVIEW_STATE.error='';
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
