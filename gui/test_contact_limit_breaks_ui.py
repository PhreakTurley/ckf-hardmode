"""Render and edit the independent contact limit-break section."""
from pathlib import Path
import sys

import serve

config = Path(serve.DEFAULT_GAME_DIR) / 'BepInEx/config'
model = serve.App({'configDirOverride': str(config)}, 'test-token').api_model()
model['contactBreaks']['document'] = {'format': 1, 'minimum': 1, 'maximum': 1, 'readyThreshold': 15}

ASSERTIONS = r'''
setTimeout(function () {
  let passed=0;
  function ck(name, ok) {if (!ok) throw new Error(name);passed++;console.log('PASS '+name);}
  ck('contacts have their own navigation section', $('#index').textContent.includes('Faster Contact Limit Breaks'));
  SEL='contact-breaks';render();
  const panel=$('#panel');
  const low=panel.querySelector('#contact-minimum'), high=panel.querySelector('#contact-maximum'), threshold=panel.querySelector('#contact-readyThreshold');
  ck('two turn controls and a ready-contact threshold are displayed', panel.find(function(n) {return n.tagName==='INPUT' && n.getAttribute('type')==='number';}).length===3);
  ck('all exact rule identities are displayed', panel.textContent.includes('Rule 84') && panel.textContent.includes('Rule 85') && panel.textContent.includes('Rule 86'));
  ck('both saved values are one', low.value==='1' && high.value==='1');
  const rules=MODEL.playerBalance.pages.find(function(p) {return p.id==='rules';});
  ck('contact rules cannot enter Player Balance export', rules.grids.every(function(g) {return !g.rows.some(function(r) {return ['84','85','86'].includes(r.id);});}));
  high.value='3';high.fire('input');
  ck('editing maximum preserves minimum', buildEdits().contactBreaks.minimum===1 && buildEdits().contactBreaks.maximum===3);
  ck('contact edits never change the party maximum', !buildEdits().partySize && !buildEdits().playerBalance);
  ck('pending edits block contact export', panel.querySelector('#send-contact').disabled);
  high.value='1';high.fire('input');
  ck('restoring turns clears the edit', !contactChanged() && !buildEdits().contactBreaks);
  ck('threshold displays its saved value and label', threshold.value==='15' && panel.textContent.includes('Contact ready threshold'));
  threshold.value='7';threshold.fire('input');
  ck('threshold saves with both existing waits', buildEdits().contactBreaks.readyThreshold===7
    && buildEdits().contactBreaks.minimum===1 && buildEdits().contactBreaks.maximum===1);
  ck('threshold edits stay in the contact mod', !buildEdits().partySize && !buildEdits().playerBalance);
  threshold.value='15';threshold.fire('input');
  ck('restoring threshold clears its edit', !contactChanged() && !buildEdits().contactBreaks);
  console.log('Contact limit-break UI: '+passed+' passed');process.exit(0);
}, 0);
'''

if __name__ == '__main__':
    sys.exit(serve.selftest_dom(model, ASSERTIONS))
