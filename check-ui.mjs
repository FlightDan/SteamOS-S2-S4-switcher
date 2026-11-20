import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
const metadata = JSON.parse(fs.readFileSync(new URL('./plugin.json', import.meta.url), 'utf8'));
assert.equal(metadata.name, 'Boiler S2-S4 switcher');
const deckyModule = new URL(`/plugins/${metadata.name}/dist/index.js`, 'http://127.0.0.1:1337');
assert.equal(deckyModule.pathname.split('/').length, 5);
const source = fs.readFileSync(new URL('./dist/index.js', import.meta.url), 'utf8').replace(/export default\s*/, 'globalThis.plugin=');
function harness(language, initial, steamLanguage) {
  const slots = [], effects = [], calls = [];
  let index = 0, tree, state = {...initial}, fail = false;
  const R = { createElement: (type, props, ...children) => ({type, props: props || {}, children}),
    useState: value => { const i = index++; if (!(i in slots)) slots[i] = value; return [slots[i], v => { slots[i] = v; }]; },
    useEffect: fn => effects.push(fn) };
  const context = vm.createContext({navigator: {language}, URLSearchParams, DFL: steamLanguage ? {findSP: () => ({location: {search: `?LANGUAGE=${steamLanguage}`}})} : undefined, window: {SP_REACT: R,
    DFL: {PanelSection:'section', PanelSectionRow:'row', ToggleField:'toggle', SliderField:'slider', ButtonItem:'button'},
    __DECKY_SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED_deckyLoaderAPIInit: {connect: (version, name) => { assert.equal(version, 2); assert.equal(name, metadata.name); return {callable: name => async (...args) => {
      if (name === 'get_sleep_status') return state;
      calls.push([name, ...args]);
      if (fail) throw Error('operation failed');
      if (name === 'set_enabled') state = {...state,enabled:args[0]};
      else state = {...state,mode:args[0],delay_minutes:args[1]};
      return state;
    }}; }}}});
  vm.runInContext(source, context);
  assert.equal(context.plugin().titleView.children[0], 'Boiler S2/S4 switcher');
  const render = () => {index=0; tree=context.plugin().content.type();};
  const find = (key, node=tree) => {
    if (Array.isArray(node)) { for (const n of node) {const result=find(key,n); if (result) return result;} return; }
    if (!node || typeof node !== 'object') return;
    if (node.props?.key === key) return node.children[0];
    return find(key,node.children);
  };
  return {calls, render, find, fail: () => {fail=true;}, async mount() {render(); effects.forEach(fn=>fn()); for (let i=0;i<5;i++) await Promise.resolve(); render();}};
}
const base = {enabled:false,mode:'auto',delay_minutes:120,router_installed:true,ready:true,available_modes:['system','s2idle','hibernate','auto'],reasons:{}};
for (const language of ['en-US','zh-CN','zh-TW','ja','ko','de','fr','es']) {
  const ui=harness(language,base); await ui.mount();
  assert.equal(ui.find('switch').props.checked,false);
  assert.equal(ui.find('delay').props.disabled,true);
  assert.equal(ui.calls.length,0);
  await ui.find('switch').props.onChange(true); ui.render();
  assert.equal(ui.find('switch').props.checked,true);
  assert.equal(ui.find('delay').props.disabled,false);
  ui.find('delay').props.onChange(0); ui.render();
  assert.equal(ui.calls.length,1);
  await ui.find('save').props.onClick(); ui.render();
  assert.deepEqual(ui.calls[1],['set_sleep_policy','hibernate',120]);
  ui.find('delay').props.onChange(5); ui.render();
  await ui.find('save').props.onClick(); ui.render();
  assert.deepEqual(ui.calls[2],['set_sleep_policy','auto',1440]);
  await ui.find('switch').props.onChange(false); ui.render();
  assert.equal(ui.find('delay').props.disabled,true);
  assert.deepEqual(ui.calls[3],['set_enabled',false]);
}
const expectedLabels = {'en-US':'Enable S4 sleep','zh-CN':'开启 S4 睡眠','zh-TW':'開啟 S4 休眠','ja':'S4 休止を有効にする','ko':'S4 최대 절전 사용','de':'S4-Ruhezustand aktivieren','fr':'Activer l’hibernation S4','es':'Activar hibernación S4'};
for (const [language, label] of Object.entries(expectedLabels)) {
  const ui=harness(language,{...base,enabled:true,required_swap_bytes:1048577,mode:'auto',delay_minutes:30}); await ui.mount();
  assert.equal(ui.find('switch').props.label,label,language);
  assert(ui.find('explanation').children.join('').includes('2 MiB'), language + ' interpolates swap size');
  assert(ui.find('delay').props.renderValue(ui.find('delay').props.value).includes('30'), language + ' interpolates legacy minutes');
}
const steam=harness('en-US',base,'tchinese'); await steam.mount();
assert.equal(steam.find('switch').props.label,expectedLabels['zh-TW'],'Steam language overrides navigator');
const fallback=harness('it-IT',base); await fallback.mount();
assert.equal(fallback.find('switch').props.label,expectedLabels['en-US']);
const localizedReason=harness('ja',{...base,enabled:true,available_modes:['system'],reasons:{hibernate:['policy_disabled']}}); await localizedReason.mount();
localizedReason.find('delay').props.onChange(0); localizedReason.render();
assert(localizedReason.find('status').children.join('').includes('システム設定で休止が無効です'));
const newReasons = ['cmdline_unavailable','external_resume','efivars_unavailable','pending_efi_location','resume_configured','resume_unavailable','other_swap','systemd_unsupported','filesystem_unsupported'];
for (const language of Object.keys(expectedLabels)) {
  for (const reason of newReasons) {
    const ui=harness(language,{...base,enabled:true,available_modes:['system'],reasons:{hibernate:[reason]}}); await ui.mount();
    ui.find('delay').props.onChange(0); ui.render();
    const text=ui.find('status').children.join('');
    assert(!text.includes(reason), `${language} must display a message for ${reason}`);
  }
}
const legacy=harness('en-US',{...base,enabled:true,mode:'auto',delay_minutes:30}); await legacy.mount();
assert.equal(legacy.find('delay').props.renderValue(legacy.find('delay').props.value),'30 min');
await legacy.find('save').props.onClick(); assert.deepEqual(legacy.calls[0],['set_sleep_policy','auto',30]);
const blocked=harness('en-US',{...base,enabled:true,available_modes:['system'],reasons:{hibernate:['policy_disabled']}}); await blocked.mount();
blocked.find('delay').props.onChange(0); blocked.render(); assert.equal(blocked.find('save').props.disabled,true);
const failed=harness('en-US',{...base,enabled:true}); await failed.mount(); failed.fail();
await failed.find('switch').props.onChange(false); failed.render();
assert.equal(failed.find('switch').props.checked,true, 'failed cleanup retains live enabled state');
assert(failed.find('error'));
const inactive=harness('en-US',{...base,router_installed:false}); await inactive.mount();
assert.equal(inactive.find('switch').props.disabled,true);
console.log('UI smoke passed: eight languages, confirmed enable/disable, failure readback, explicit save, six positions, legacy delay and capability gating.');
