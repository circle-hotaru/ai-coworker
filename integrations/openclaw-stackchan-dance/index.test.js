import test from 'node:test';
import assert from 'node:assert/strict';
import plugin from './index.js';
const registry = [];
plugin.register({registerTool(factory, options) { registry.push({factory,options}); }});
test('only Operator receives the three declared hardware tools', () => {
  assert.deepEqual(registry.map(x => x.options.name), ['stackchan_dance_start','stackchan_dance_stop','stackchan_dance_status']);
  for (const x of registry) {
    assert.equal(x.factory({agentId:'reviewer'}), null);
    assert.equal(x.factory({agentId:'researcher'}), null);
    assert.equal(x.factory({agentId:'operator'}).name,x.options.name);
  }
});
test('stop forwards exactly one immediate request and returns firmware state', async () => {
  const calls=[];globalThis.fetch=async (url,options)=>{calls.push([url,options.method]);return {ok:true,json:async()=>({device:'Operator',state:'returning'})};};
  const r=await registry[1].factory({agentId:'operator'}).execute();
  assert.equal(r.isError,false);assert.equal(r.details.state,'returning');
  assert.deepEqual(calls,[['http://127.0.0.1:8003/xiaozhi/dance/stop','POST']]);
});
test('offline hardware is an error, never a successful dance', async () => {
  globalThis.fetch=async()=>({ok:false,json:async()=>({error:'offline'})});
  const r=await registry[0].factory({agentId:'operator'}).execute();assert.equal(r.isError,true);
  globalThis.fetch=async()=>{throw new Error('timeout');};
  assert.equal((await registry[0].factory({agentId:'operator'}).execute()).isError,true);
});
