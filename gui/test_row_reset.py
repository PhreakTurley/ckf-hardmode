"""Row-wide resets preserve identities and use the existing guarded save paths."""
import sys

import serve


ASSERTIONS = r'''
setTimeout(function () {
  let passed=0;
  function ck(name,ok) {if (!ok) throw new Error(name);passed++;console.log('PASS '+name);}
  const savedW=JSON.parse(JSON.stringify(W));
  const panel=$('#panel');
  function find(fn) {return panel.find(fn);}
  function button(table,id) {return find(n=>n.tagName==='BUTTON' && n.getAttribute('aria-label')==='Reset '+table+' '+id)[0];}
  function column(name,extra) {return Object.assign({name:name,label:name,order:0,integer:true,always:true},extra);}
  const grid={table:'Weapon',title:'Fixture',columns:[column('Cost')],advanced:[column('Hidden')],rows:[
    {id:'1',name:'Shared gear',enemyUse:true,baseline:{Cost:'10',Hidden:'0'}},
    {id:'2',name:'Other gear',baseline:{Cost:'20',Hidden:'0'}}]};
  W.player.tables.Weapon={'1':{Cost:'=0',Hidden:'x2'},'2':{Cost:'=99'}};
  W.player.tables.Armor={'1':{Cost:'=33'}};
  MODEL.playerBalance.document.tables.Weapon=JSON.parse(JSON.stringify(W.player.tables.Weapon));
  const page={id:'reset-fixture',title:'Reset fixture',grids:[grid]};
  panel.textContent='';renderPlayer(panel,page);
  const row=find(n=>n.getAttribute('data-player-row')==='Weapon 1')[0];
  ck('reset is small and directly left of Name', row.children[0].children[0]===button('Weapon','1')
    && row.children[1]._cls().includes('pb-name') && button('Weapon','1')._cls().includes('row-reset'));
  const marker=row.children[1].find(n=>n._cls().includes('pb-enemy-icon'))[0];
  ck('shared gear warning is an accessible inline icon', marker && marker.textContent==='⚔'
    && marker.getAttribute('aria-label')==='Also used by enemies' && marker.title.includes('affects enemies')
    && !row.find(n=>n._cls().includes('pb-enemy')).length);
  button('Weapon','1').fire('click');
  ck('row reset clears zero and hidden overrides', !W.player.tables.Weapon['1']);
  ck('reset preserves other rows and same ids in other tables', W.player.tables.Weapon['2'].Cost==='=99'
    && W.player.tables.Armor['1'].Cost==='=33');
  ck('saved overrides become explicit clear edits', ['Cost','Hidden'].every(column=>
    playerChanges().cells.some(c=>c.table==='Weapon' && c.id==='1' && c.column===column && c.value==='')));
  const joined={table:'Weapon',title:'Joined',columns:[column('Linked'),column('Protected')],advanced:[],rows:[
    {id:'1',name:'Joined gear',baseline:{Linked:'5',Protected:'3'},targets:{
      Linked:{table:'Talent',id:'1',column:'ApCost'},Protected:{table:'Effect',id:'1',column:'Heals',readOnly:true}}}]};
  W.player.tables.Weapon['1']={Cost:'=20'};
  W.player.tables.Talent={'1':{ApCost:'=7'}};W.player.tables.Effect={'1':{Heals:'=9'}};
  panel.textContent='';renderPlayer(panel,{id:'joined-reset',title:'Joined',grids:[joined]});button('Weapon','1').fire('click');
  ck('joined reset clears native and linked editable fields', !W.player.tables.Weapon['1'] && !W.player.tables.Talent);
  ck('joined reset preserves managed fields', W.player.tables.Effect['1'].Heals==='=9');
  const consumable={table:'Item',title:'Items',columns:[column('Cost')],advanced:[],
    consumableEditor:{tagColumn:'ItemClass',modelColumn:'Asset3DTypeId',talentTable:'Talent',iconColumn:'IconPng',
      talentAssetColumn:'Asset3DTypeId',tags:[],families:{},modelAssets:{}},rows:[
      {id:'9',name:'Item',baseline:{Cost:'10'},acquisition:['Fixture'],consumable:{classBase:'4',modelBase:'0',
        talent:{id:'75014',iconBase:'original',assetBase:'0',sharedWith:[]}}}]};
  W.player.tables.Item={'9':{Cost:'17',ItemClass:'1',Asset3DTypeId:'1002'}};
  W.player.tables.Talent={'75014':{IconPng:'edited',Asset3DTypeId:'1004'}};
  W.player.implantMultipliers.Cost=2;
  const refresh=refreshConsumableViews;let destination;
  refreshConsumableViews=function(to) {destination=to;};
  panel.textContent='';renderPlayer(panel,{id:'item-reset',title:'Items',grids:[consumable]});button('Item','9').fire('click');
  ck('consumable reset clears stats, tag and linked visuals', !W.player.tables.Item && !W.player.tables.Talent);
  ck('tag reset refreshes the original category', destination==='consumable-4');
  ck('row reset preserves global multipliers', W.player.implantMultipliers.Cost===2);
  refreshConsumableViews=refresh;
  const enemy={table:'Armor',title:'Clones',columns:[column('BallisticArmor')],advanced:[column('PhysicalArmor')],rows:[
    {id:'990001',name:'Clone',cloneOf:'22000',origin:'Clone',baseline:{BallisticArmor:'45',PhysicalArmor:'15'},targets:{
      BallisticArmor:{table:'Armor',id:'990001',column:'BallisticArmor',enemyArmor:true},
      PhysicalArmor:{table:'Armor',id:'990001',column:'PhysicalArmor',enemyArmor:true}}}]};
  W.enemyArmor['990001']={BallisticArmor:'0',PhysicalArmor:'27'};
  MODEL.enemyArmor.values['990001']={BallisticArmor:'0',PhysicalArmor:'27'};
  panel.textContent='';renderPlayer(panel,{id:'clone-reset',title:'Clones',enemyArmor:true,grids:[enemy]});button('Armor','990001').fire('click');
  ck('clone resets all native fields', W.enemyArmor['990001'].BallisticArmor==='' && W.enemyArmor['990001'].PhysicalArmor==='');
  ck('clone remains present with its donor', find(n=>n._cls().includes('pb-clone')).some(n=>n.textContent==='Clone 990001 (from 22000)')
    && enemy.rows[0].cloneOf==='22000');
  ck('clone reset uses enemy save payload', enemyArmorChanges().cells.filter(c=>c.id==='990001' && c.value==='').length===2);
  const rel='reset-fixture.csv';
  const ov={present:true,writable:true,table:'Armor',kind:'direct',keyColumn:'ArmorId',
    columns:[{name:'ArmorId'},{name:'_clone',control:true},{name:'BallisticArmor',op:'set'},
      {name:'PhysicalArmor',op:'set'},{name:'_comment',control:true}],
    editable:[false,false,true,true,false],roles:['identity','control','lever','lever','control'],
    hidden:[null,null,null,'hidden fixture',null],rows:[{key:['990001'],cells:['990001','22000','0','27','keep']} ]};
  MODEL.values.overlays[rel]=ov;W.overlays[rel]={cells:ov.rows.map(r=>r.cells.slice())};
  const linkedOverlay={table:'Armor',title:'Overlay',columns:[column('BallisticArmor')],advanced:[],rows:[
    {id:'990001',name:'Authored clone',baseline:{BallisticArmor:'45'},targets:{BallisticArmor:{
      table:'Armor',id:'990001',column:'BallisticArmor',overlay:rel,row:0,ci:2}}}]};
  W.player.tables.Armor['990001']={BallisticArmor:'99'};
  panel.textContent='';renderPlayer(panel,{id:'overlay-reset',title:'Overlay',grids:[linkedOverlay]});button('Armor','990001').fire('click');
  ck('linked overlay reset clears both conflicting assignments', !W.player.tables.Armor['990001']
    && W.overlays[rel].cells[0][2]==='' && W.overlays[rel].cells[0][1]==='22000');
  W.overlays[rel].cells=ov.rows.map(r=>r.cells.slice());
  panel.textContent='';panel.appendChild(overlayBlock({},rel));button('Armor','990001').fire('click');
  ck('overlay reset clears hidden values and preserves clone controls',
    JSON.stringify(W.overlays[rel].cells[0])===JSON.stringify(['990001','22000','','','keep']));
  W=savedW;
  console.log('Row reset UI: '+passed+' passed');process.exit(0);
},0);
'''


if __name__ == '__main__':
    sys.exit(serve.selftest_dom(serve.App(serve.load_settings(), 'test-token').api_model(), ASSERTIONS))
