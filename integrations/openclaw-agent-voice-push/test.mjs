import assert from 'node:assert/strict';
import {extract,extractSent,extractTool,chunks} from './index.js';
const ctx={agentId:'reviewer',sessionKey:'agent:reviewer:openai-user:test',runId:'r1'};
const event={success:true,messages:[{role:'assistant',content:[{type:'thinking',thinking:'private'},{type:'text',text:'后续回复'}],stopReason:'stop'}]};
assert.equal(extract(event,ctx).text,'后续回复');
assert.equal(extract(event,{...ctx,agentId:'operator'}),null);
assert.equal(extract(event,{...ctx,sessionKey:'agent:reviewer:main'}),null);
assert.equal(extract({...event,success:false},ctx),null);
assert.equal(extract({success:true,messages:[{role:'assistant',stopReason:'toolUse',content:[{type:'text',text:'working'}]}]},ctx),null);
assert.equal(extract({success:true,messages:[{role:'assistant',content:'NO_REPLY'}]},ctx),null);
console.log('6 plugin filter assertions passed');

assert.equal(extractSent({success:true,runId:'r2',content:'主动消息',sessionKey:ctx.sessionKey},{}).text,'主动消息');
assert.equal(extractSent({success:true,runId:'r2',content:'private',sessionKey:'agent:reviewer:main'},{}),null);
assert.equal(extractSent({success:true,content:'missing run',sessionKey:ctx.sessionKey},{}),null);
console.log('3 message delivery assertions passed');

const long='长回复🙂'.repeat(2000); const parts=chunks(long);
assert.equal(parts.join(''),long);
assert(parts.every(part=>Buffer.byteLength(part)<=4500));
assert(parts.length>1);
console.log('3 long reply assertions passed');

const operator={...ctx,agentId:'operator',sessionKey:'agent:operator:openai-user:test'};
assert.equal(extract(event,operator).text,'后续回复');
assert.equal(extractSent({success:true,runId:'w',content:'执行同事更新',sessionKey:operator.sessionKey},{}).text,'执行同事更新');
assert.equal(extract(event,{...operator,agentId:'researcher'}),null);
console.log('3 Operator routing assertions passed');

const tool={toolName:'message',runId:'internal-run',result:{isError:false,details:{status:'ok',deliveryStatus:'sent',sourceReplySink:'internal-ui',target:'current-run',sourceReply:{text:'内部消息回复'},dryRun:false}}};
assert.equal(extractTool(tool,operator).text,'内部消息回复');
assert.equal(extractTool({...tool,error:'failed'},operator),null);
assert.equal(extractTool({...tool,result:{...tool.result,isError:true}},operator),null);
assert.equal(extractTool({...tool,result:{details:{...tool.result.details,dryRun:true}}},operator),null);
assert.equal(extractTool({...tool,result:{details:{...tool.result.details,sourceReplySink:'external-channel'}}},operator),null);
assert.equal(extractTool({...tool,result:{details:{...tool.result.details,target:'another-person'}}},operator),null);
assert.equal(extractTool(tool,{...operator,sessionKey:'agent:operator:main'}),null);
assert.equal(extractTool({...tool,toolName:'sessions_send'},operator),null);
console.log('8 internal source delivery assertions passed');

const researcher={...ctx,agentId:'researcher',sessionKey:'agent:researcher:openai-user:test'};
assert.equal(extract(event,researcher).text,'后续回复');
assert.equal(extractSent({success:true,runId:'m',content:'研究同事更新',sessionKey:researcher.sessionKey},{}).text,'研究同事更新');
assert.equal(extractTool(tool,researcher).text,'内部消息回复');
assert.equal(extractTool(tool,{...researcher,sessionKey:'agent:researcher:main'}),null);
console.log('4 Researcher routing assertions passed');
