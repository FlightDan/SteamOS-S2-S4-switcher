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
  let index = 0, tree, state = {...initial}, failure = null, beforeSave, rejectAfterSave = false;
  const R = { createElement: (type, props, ...children) => ({type, props: props || {}, children}),
    useState: value => { const i = index++; if (!(i in slots)) slots[i] = value; return [slots[i], v => { slots[i] = v; }]; },
    useRef: value => { const i = index++; return slots[i] ??= {current: value}; },
    useEffect: fn => effects.push(fn) };
  const context = vm.createContext({navigator: {language}, URLSearchParams, DFL: steamLanguage ? {findSP: () => ({location: {search: `?LANGUAGE=${steamLanguage}`}})} : undefined, window: {SP_REACT: R,
    DFL: {PanelSection:'section', PanelSectionRow:'row', ToggleField:'toggle', SliderField:'slider', ButtonItem:'button'},
    __DECKY_SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED_deckyLoaderAPIInit: {connect: (version, name) => { assert.equal(version, 2); assert.equal(name, metadata.name); return {callable: name => async (...args) => {
      if (name === 'get_sleep_status') return state;
      calls.push([name, ...args]);
      if (name === 'set_sleep_policy' && beforeSave) await beforeSave();
      if (failure) throw Error(failure);
      if (name === 'set_enabled') state = {...state,enabled:args[0]};
      else state = {...state,mode:args[0],delay_minutes:args[1]};
      if (name === 'set_sleep_policy' && rejectAfterSave) {
        rejectAfterSave = false;
        throw Error('save response lost');
      }
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
  return {calls, render, find, policy: () => [state.mode, state.delay_minutes],
    fail: (message = 'operation failed') => {failure = message;},
    loseNextSaveResponse: () => {rejectAfterSave = true;},
    pauseNextSave() {
      let release;
      const wait = new Promise(resolve => {release = resolve;});
      beforeSave = () => {beforeSave = null; return wait;};
      return release;
    },
    async mount() {render(); effects.forEach(fn=>fn()); for (let i=0;i<5;i++) await Promise.resolve(); render();}};
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
  assert.equal(ui.find('save'),undefined);
  await ui.find('delay').props.onChange(0); ui.render();
  assert.deepEqual(ui.calls[1],['set_sleep_policy','hibernate',120]);
  await ui.find('delay').props.onChange(5); ui.render();
  assert.deepEqual(ui.calls[2],['set_sleep_policy','auto',1440]);
  await ui.find('switch').props.onChange(false); ui.render();
  assert.equal(ui.find('delay').props.disabled,true);
  assert.deepEqual(ui.calls[3],['set_enabled',false]);
}
const expectedLabels = {'en-US':'Enable S4 sleep','zh-CN':'开启 S4 睡眠','zh-TW':'開啟 S4 休眠','ja':'S4 休止を有効にする','ko':'S4 최대 절전 사용','de':'S4-Ruhezustand aktivieren','fr':'Activer l’hibernation S4','es':'Activar hibernación S4'};
for (const [language, label] of Object.entries(expectedLabels)) {
  const ui=harness(language,{...base,enabled:true,required_swap_bytes:31613 * 1048576,mode:'auto',delay_minutes:30}); await ui.mount();
  assert.equal(ui.find('switch').props.label,label,language);
  const explanation = ui.find('explanation').children.join('');
  assert(explanation.includes('31613 MB'), language + ' interpolates swap size');
  if (language === 'zh-CN') assert.equal(explanation,'开启 S4 睡眠后需要 31613 MB 空间创建交换文件');
  assert.equal(ui.find('status'),undefined,'ready mode has no status blurb');
  assert.equal(ui.find('save'),undefined);
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
assert.deepEqual(legacy.calls,[]);
assert.deepEqual(legacy.policy(),['auto',30]);
await legacy.find('delay').props.onChange(3); assert.deepEqual(legacy.calls[0],['set_sleep_policy','auto',120]);
const blocked=harness('en-US',{...base,enabled:true,available_modes:['system'],reasons:{hibernate:['policy_disabled']}}); await blocked.mount();
await blocked.find('delay').props.onChange(0); blocked.render();
assert.deepEqual(blocked.calls,[]);
assert(blocked.find('status').children.join('').includes('Selected mode unavailable'));
const rapid=harness('en-US',{...base,enabled:true}); await rapid.mount();
const finishFirst=rapid.pauseNextSave();
const writing=rapid.find('delay').props.onChange(1); rapid.render();
assert.equal(rapid.find('switch').props.disabled,true);
assert.equal(rapid.find('delay').props.disabled,false);
rapid.find('delay').props.onChange(4);
rapid.find('delay').props.onChange(0);
rapid.render();
assert.equal(rapid.find('delay').props.value,0);
assert.deepEqual(rapid.calls,[['set_sleep_policy','auto',20]]);
finishFirst(); await writing; rapid.render();
assert.deepEqual(rapid.calls,[['set_sleep_policy','auto',20],['set_sleep_policy','hibernate',20]]);
assert.deepEqual(rapid.policy(),['hibernate',20]);
assert.equal(rapid.find('delay').props.value,0);
assert.equal(rapid.find('switch').props.disabled,false);
const lostResponse=harness('en-US',{...base,enabled:true}); await lostResponse.mount();
const finishLost=lostResponse.pauseNextSave(); lostResponse.loseNextSaveResponse();
const lostWrite=lostResponse.find('delay').props.onChange(2); lostResponse.render();
lostResponse.find('delay').props.onChange(3);
finishLost(); await lostWrite; lostResponse.render();
assert.deepEqual(lostResponse.calls,[['set_sleep_policy','auto',60],['set_sleep_policy','auto',120]]);
assert.deepEqual(lostResponse.policy(),['auto',120]);
assert.equal(lostResponse.find('error'),undefined);
const saveFailed=harness('en-US',{...base,enabled:true,delay_minutes:30}); await saveFailed.mount(); saveFailed.fail();
await saveFailed.find('delay').props.onChange(5); saveFailed.render();
assert.deepEqual(saveFailed.policy(),['auto',30]);
assert.equal(saveFailed.find('delay').props.renderValue(saveFailed.find('delay').props.value),'30 min');
assert(saveFailed.find('error'));
const failed=harness('en-US',{...base,enabled:true}); await failed.mount(); failed.fail();
await failed.find('switch').props.onChange(false); failed.render();
assert.equal(failed.find('switch').props.checked,true, 'failed cleanup retains live enabled state');
assert(failed.find('error'));
const noSpace=harness('zh-CN',base); await noSpace.mount(); noSpace.fail('Error: Insufficient free space for swap and 500 MiB reserve');
await noSpace.find('switch').props.onChange(true); noSpace.render();
assert.equal(noSpace.find('error').children.join(''),'请先腾出空间创建 S4 交换文件，再重试。');
const inactive=harness('en-US',{...base,router_installed:false}); await inactive.mount();
assert.equal(inactive.find('switch').props.disabled,true);
console.log('UI smoke passed: eight languages, swap copy, automatic persistence, rapid changes, failure recovery, legacy delay and capability gating.');
