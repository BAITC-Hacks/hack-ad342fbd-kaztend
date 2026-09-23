// Регрессионные проверки асинхронного состояния без браузерных зависимостей.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const script = fs.readFileSync(path.join(__dirname, '../frontend/index.html'), 'utf8')
  .split('<script>')[1].split('</script>')[0].replace('runAction(null, init);', '');

function harness(){
  const nodes = new Map();
  function node(id){
    if (!nodes.has(id)) nodes.set(id, {value:'', textContent:'', innerHTML:'', disabled:false,
      style:{}, classList:{toggle(){}, add(){}, remove(){}}, querySelectorAll(){return []},
      options:[], selectedOptions:[], appendChild(){}, remove(){}, scrollIntoView(){}});
    return nodes.get(id);
  }
  const requests = [], downloads = [];
  const ctx = vm.createContext({document:{querySelector:node, querySelectorAll(){return []}, createElement:()=>node('created')},
    setTimeout, URL, Blob,
    fetch: (url, options) => new Promise(resolve => requests.push({url, body:JSON.parse(options?.body || 'null'), resolve(value){
      resolve({ok:true, headers:{get:()=>typeof value === 'string'?'text/plain':'application/json'}, json:async()=>value, text:async()=>value});
    }}))});
  vm.runInContext(script, ctx);
  ctx.downloads = downloads;
  vm.runInContext(`
    catalog = {budget:100, measures:[{id:'M7', cost:24, scope:'Район'}, {id:'M8', cost:20, scope:'Район'},
      {id:'M10',cost:12,scope:'Район'}, {id:'M12',cost:14,scope:'Город'}, {id:'M5',cost:25,scope:'Район'}],
      baseline:{score:52.56}, events:[{id:'smog',baseline:{score:51}}]};
    renderGauge = ()=>{}; renderMap = ()=>{}; renderPareto = ()=>{};
    download = (content,type,filename)=>downloads.push({content,type,filename});
    for (let i=0;i<5;i++){ $('#m'+i).value=PRESET[i][0]; $('#d'+i).value=PRESET[i][1]||''; }
  `, ctx);
  return {ctx,node,requests,downloads,run:code=>vm.runInContext(code,ctx)};
}
const tick = () => new Promise(resolve=>setImmediate(resolve));

test('editing or reset clears calculated data, explanations and export eligibility', ()=>{
  const h=harness();
  h.run(`lastResult={valid:true,score:56.54}; resultSnapshot=captureScenario(); lastExplanation={summary:'old'}; explanationScenarioId='old';`);
  assert.equal(h.run('Boolean(canExport())'),true);
  h.node('#d0').value='Есиль'; h.run('invalidateScenario()');
  assert.equal(h.run('lastResult'),null);
  assert.equal(h.run('lastExplanation'),null);
  assert.equal(h.node('#btnJson').disabled,true);
  assert.equal(h.node('#btnReport').disabled,true);
  h.run('exportJson()'); assert.equal(h.downloads.length,0);
});

test('a late simulation response cannot restore old results', async()=>{
  const h=harness(); const pending=h.run('simulateNow()');
  h.requests[0].resolve({valid:true, errors:[]}); await tick();
  assert.equal(h.requests[1].url,'/api/simulate');
  h.node('#eventSelect').value='smog'; h.run('invalidateScenario()');
  h.requests[1].resolve({valid:true,score:56.54});
  assert.equal(await pending,null);
  assert.equal(h.run('lastResult'),null);
  assert.equal(h.node('#btnJson').disabled,true);
});

test('a late explanation cannot reappear after scenario changes', async()=>{
  const h=harness(); const pending=h.run('explainNow()');
  h.requests[0].resolve({valid:true,errors:[]}); await tick();
  h.node('#d0').value='Алматы'; h.run('invalidateScenario()');
  h.requests[1].resolve({valid:true,explanation:{summary:'old'},scenario_id:'old'});
  await pending;
  assert.equal(h.run('lastExplanation'),null);
  assert.equal(h.node('#explainOut').textContent,'');
});

test('a late validation response cannot replace current validation', async()=>{
  const h=harness(); const old=h.run('liveValidate()');
  h.node('#d0').value='Алматы'; h.run('invalidateScenario()');
  const current=h.run('liveValidate()');
  h.requests[1].resolve({valid:true,errors:[]}); await current;
  h.requests[0].resolve({valid:false,errors:['stale error']}); await old;
  assert.equal(h.node('#errors').innerHTML,'');
});

test('JSON and report use the calculated snapshot and matching explanation ID', async()=>{
  const h=harness();
  h.run(`lastResult={valid:true,score:56.54,scenario_id:'sample'}; resultSnapshot=captureScenario();
    lastExplanation={summary:'current'}; explanationScenarioId='sample'; exportJson();`);
  const out=JSON.parse(h.downloads[0].content);
  assert.equal(out.result.score,56.54);
  assert.equal(out.decisions[0].district,'Нура');
  assert.equal(out.explanation_scenario_id,'sample');
  const pending=h.run('exportReport()');
  assert.equal(h.requests[0].body.explanation_scenario_id,'sample');
  h.node('#eventSelect').value='smog'; h.run('invalidateScenario()');
  h.requests[0].resolve('obsolete report'); await pending;
  assert.equal(h.downloads.length,1);
});

test('event and language changes invalidate previously captured snapshots', ()=>{
  const h=harness(); h.run('var captured=captureScenario()');
  h.node('#eventSelect').value='smog';
  assert.equal(h.run('isCurrent(captured)'),false);
  h.node('#eventSelect').value=''; h.run("lang='kz'");
  assert.equal(h.run('isCurrent(captured)'),false);
});
