"""Render and edit the independent contact limit-break section."""
from pathlib import Path
import sys

import serve

config = Path(serve.DEFAULT_GAME_DIR) / 'BepInEx/config'
model = serve.App({'configDirOverride': str(config)}, 'test-token').api_model()
model['contactBreaks']['document'] = {'format': 1, 'minimum': 1, 'maximum': 1}

ASSERTIONS = r'''
setTimeout(function () {
  let passed=0;
  function ck(name, ok) {if (!ok) throw new Error(name);passed++;console.log('PASS '+name);}
  ck('contacts have their own navigation section', $('#index').textContent.includes('Faster Contact Limit Breaks'));
  SEL='contact-breaks';render();
  const panel=$('#panel');
  const low=panel.querySelector('#contact-minimum'), high=panel.querySelector('#contact-maximum');
  ck('two turn controls are displayed', panel.find(function(n) {return n.tagName==='INPUT' && n.getAttribute('type')==='number';}).length===2);
  ck('both exact rule identities are displayed', panel.textContent.includes('Rule 84') && panel.textContent.includes('Rule 85'));
  ck('both saved values are one', low.value==='1' && high.value==='1');
  const rules=MODEL.playerBalance.pages.find(function(p) {return p.id==='rules';});
  ck('contact rules cannot enter Player Balance export', rules.grids.every(function(g) {return !g.rows.some(function(r) {return r.id==='84' || r.id==='85';});}));
  high.value='3';high.fire('input');
  ck('editing maximum preserves minimum', buildEdits().contactBreaks.minimum===1 && buildEdits().contactBreaks.maximum===3);
  ck('contact edits never change the party maximum', !buildEdits().partySize && !buildEdits().playerBalance);
  ck('pending edits block contact export', panel.querySelector('#send-contact').disabled);
  high.value='1';high.fire('input');
  ck('restoring turns clears the edit', !contactChanged() && !buildEdits().contactBreaks);
  console.log('Contact limit-break UI: '+passed+' passed');process.exit(0);
}, 0);
'''

if __name__ == '__main__':
    sys.exit(serve.selftest_dom(model, ASSERTIONS))
