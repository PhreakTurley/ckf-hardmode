"""Validate clears the working copy and preserves edits made during the request."""
import sys
import serve

settings = serve.load_settings()
model = serve.App(settings, 'test-token').api_model()

ASSERTIONS = r'''
setTimeout(async function () {
  let passed = 0;
  function ck(name, value) {if (!value) throw new Error(name);passed++;console.log('PASS '+name);}
  const rel=Object.keys(MODEL.values.overlays).find(function(p) {
    return p.includes('/EffectModel.') && MODEL.values.overlays[p].writable;
  });
  const entry=MODEL.values.overlays[rel], ri=0, ci=entry.editable.findIndex(Boolean);
  entry.rows[ri].cells[ci]='1234';
  MODEL.playerBalance.document.tables={Weapon:{'1':{Cost:'99'}}};
  MODEL.enemyArmor.values['22000']={BallisticArmor:'45'};
  W=buildWorking();
  const cells=[{kind:'overlay',path:rel,key:entry.rows[ri].key,column:entry.columns[ci].name},
               {kind:'player',table:'Weapon',id:'1',column:'Cost'},
               {kind:'enemyArmor',id:'22000',column:'BallisticArmor'}];
  let request;
  api=async function(path,body) {
    if (path!=='/api/validate') throw new Error('Unexpected '+path);
    request=body;
    return {ok:true,check:{ran:true,problems:[]},cleared:cells,notes:[]};
  };
  await $('#revalidate').listeners.click[0]();
  ck('Validate sends the current fingerprints', CKF.deepEqual(request.fingerprints,MODEL.fingerprints));
  ck('native override is cleared in the working copy', W.overlays[rel].cells[ri][ci]==='');
  ck('player override is removed from the working document', !W.player.tables.Weapon);
  ck('enemy armor override is cleared in the working copy', W.enemyArmor['22000'].BallisticArmor==='');
  ck('the saved model remains unchanged until Save', entry.rows[ri].cells[ci]==='1234' && MODEL.playerBalance.document.tables.Weapon['1'].Cost==='99');
  const edits=buildEdits();
  ck('Save will persist the native cell removal', edits.overlays[rel].cells.some(c=>c.column===entry.columns[ci].name && c.value===''));
  ck('Save will persist the player cell removal', edits.playerBalance.cells.some(c=>c.table==='Weapon' && c.id==='1' && c.column==='Cost' && c.value===''));
  api=async function() {
    W.overlays[rel].cells[ri][ci]='newer edit';
    return {ok:true,check:{ran:true,problems:[]},cleared:cells,notes:[]};
  };
  await $('#revalidate').listeners.click[0]();
  ck('an edit made during validation is preserved', W.overlays[rel].cells[ri][ci]==='newer edit');
  ck('the page requests validation of the newer edit', $('#banners').textContent.includes('Edits changed during validation'));
  console.log('Override cleanup UI: '+passed+' passed');process.exit(0);
},0);
'''

if __name__ == '__main__':
    sys.exit(serve.selftest_dom(model, ASSERTIONS))
