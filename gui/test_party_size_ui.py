"""Render the Party Size Mod controls in the editor's Node DOM harness."""
from pathlib import Path
import sys

import serve

config = Path(serve.DEFAULT_GAME_DIR) / 'BepInEx/config'
app = serve.App({'configDirOverride': str(config)}, 'test-token')
model = app.api_model()
model['partySize']['document'] = {'format': 1, 'maximum': 6}

ASSERTIONS = r'''
setTimeout(function () {
  let passed=0;
  function ck(name, ok) {if (!ok) throw new Error(name);passed++;console.log('PASS '+name);}
  ck('Party Size Mod has its own navigation section', $('#index').textContent.includes('Party Size Mod'));
  SEL='party-size';render();
  const panel=$('#panel');
  ck('only the party maximum is editable', panel.find(function(n) {return n.tagName==='INPUT' && n.getAttribute('type')==='number';}).length===1);
  ck('the exact official rule is shown', panel.textContent.includes('Mission Max MercDefault') && panel.textContent.includes('Rule 83'));
  ck('saved six is displayed', panel.querySelector('#party-maximum').value==='6');
  ck('no unrelated rule catalog is rendered', !panel.textContent.includes('Max Character Level'));
  const rules=MODEL.playerBalance.pages.find(function(p) {return p.id==='rules';});
  ck('Player Balance cannot edit Party Size rule', rules.grids.every(function(g) {return !g.rows.some(function(r) {return r.id==='83';});}));
  panel.querySelector('#party-maximum').value='7';panel.querySelector('#party-maximum').fire('input');
  ck('party edits enter the save payload', buildEdits().partySize.maximum===7);
  ck('unsaved party edits block export', panel.querySelector('#send-party').disabled);
  ck('party edits do not change player balance', !buildEdits().playerBalance);
  panel.querySelector('#party-maximum').value='6';panel.querySelector('#party-maximum').fire('input');
  ck('restoring the value clears the edit', !partyChanged() && !buildEdits().partySize);
  console.log('Party Size UI: '+passed+' passed');process.exit(0);
}, 0);
'''

if __name__ == '__main__':
    sys.exit(serve.selftest_dom(model, ASSERTIONS))
