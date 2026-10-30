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
  ck('surprised accuracy has its Workshop owner', MODEL.playerBalance.pages.find(function(p) {return p.id==='combat';}).grids[0].rows.some(function(r) {return r.id==='22';}));
  const panel = $('#panel');
  const find = function (fn) {return panel.find(fn);};
  SEL='pb:weapon-17';render();
  ck('eye laser weapon and attack grids are separate', find(function (n) {return n.tagName==='TABLE';}).length===2);
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
  SEL='pb:traits';render();
  ck('traits are paginated', find(function(n) {return n.tagName==='BUTTON' && n.textContent==='Next' && !n.disabled;}).length>0);
  const next = find(function(n) {return n.tagName==='BUTTON' && n.textContent==='Next' && !n.disabled;})[0];
  next.fire('click');
  ck('pagination advances', panel.textContent.includes('76–'));
  const search = find(function(n) {return n.tagName==='INPUT' && n.getAttribute('type')==='search';})[0];
  search.value='Checked Out';search.fire('input');
  ck('fatigue rows are read-only in the Workshop trait catalog', find(function(n) {return n._cls().includes('readonly');}).length>0);
  SEL='pb:leverage';render();
  const leverageSearch = find(function(n) {return n.tagName==='INPUT' && n.getAttribute('type')==='search';})[0];
  leverageSearch.value='Suppressed Alarm';leverageSearch.fire('input');
  ck('leverage has readable names', panel.textContent.includes('Suppressed Alarm'));
  const all = find(function(n) {return n.tagName==='INPUT' && n.getAttribute('type')==='checkbox';})[0];
  const count = find(function(n) {return n.tagName==='TH';}).length;
  all.checked=true;all.fire('change');
  ck('advanced columns can be revealed', find(function(n) {return n.tagName==='TH';}).length>count);
  const pending = JSON.stringify(W.player);
  await $('#save').listeners.click[0]();
  ck('a refused save preserves pending edits', JSON.stringify(W.player) === pending && dirtyPaths().length > 0);
  console.log('Workshop UI: '+passed+' passed');process.exit(0);
}, 0);
'''

if __name__ == '__main__':
    sys.exit(serve.selftest_dom(model, ASSERTIONS))
