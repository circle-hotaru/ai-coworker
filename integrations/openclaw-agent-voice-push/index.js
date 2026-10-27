import {PARTICIPANTS, hardwareSession} from './settings.js';
import {CollaborationGuard} from './collaboration.js';
export function extract(event, ctx) {
  if (!PARTICIPANTS.has(ctx.agentId) || !ctx.sessionKey?.startsWith(`agent:${ctx.agentId}:openai-user:`) || !event.success) return null;
  const run = event.runId || ctx.runId;
  if (!run) return null;
  const message = [...(event.messages || [])].reverse().find(m => m?.role === 'assistant');
  if (!message || (message.stopReason && message.stopReason !== 'stop')) return null;
  const text = (typeof message.content === 'string' ? message.content : (message.content || []).filter(p => p.type === 'text').map(p => p.text).join('')).trim();
  if (!text || ['NO_REPLY','HEARTBEAT_OK'].includes(text)) return null;
  return {session: ctx.sessionKey.toLowerCase(), run, text};
}
export function extractSent(event, ctx) {
  const session = event.sessionKey || ctx.sessionKey;
  if (!event.success || !hardwareSession(session) || !event.runId) return null;
  const text = event.content?.trim();
  if (!text || ['NO_REPLY','HEARTBEAT_OK'].includes(text)) return null;
  return {session:session.toLowerCase(), run:event.runId, text};
}
export function extractTool(event, ctx) {
  const session = ctx.sessionKey;
  if (event.toolName !== 'message' || event.error || !hardwareSession(session)) return null;
  const result = event.result;
  const details = result?.details;
  // Only an acknowledged user-visible reply to this same source conversation.
  // Never forward message arguments aimed at another agent, person or channel.
  if (result?.isError || details?.status !== 'ok' || details.deliveryStatus !== 'sent' ||
      details.sourceReplySink !== 'internal-ui' || details.target !== 'current-run' || details.dryRun) return null;
  const run = event.runId || ctx.runId;
  const text = details.sourceReply?.text?.trim();
  if (!run || !text || ['NO_REPLY','HEARTBEAT_OK'].includes(text)) return null;
  return {session:session.toLowerCase(), run, text};
}
export function chunks(text, limit = 4500) {
  const result = [];
  let part = '', size = 0;
  for (const character of text) {
    const bytes = Buffer.byteLength(character);
    if (size + bytes > limit) { result.push(part); part = ''; size = 0; }
    part += character; size += bytes;
  }
  if (part) result.push(part);
  return result;
}
async function deliver(api, payload) {
  if (!payload) return;
  try {
    for (const text of chunks(payload.text)) {
    const response = await fetch('http://127.0.0.1:8003/xiaozhi/push/events', {
      method:'POST', headers:{'content-type':'application/json'}, body:JSON.stringify({...payload,text}),
      signal:AbortSignal.timeout(4000), redirect:'error'
    });
    if (!response.ok && response.status !== 403) api.logger.warn(`Voice followup queue returned ${response.status}`);
    }
  } catch { api.logger.warn('Voice followup bridge unavailable'); }
}
export default {
  id: 'agent-voice-push', name: 'Hardware Voice Followups',
  register(api) {
    const guard = new CollaborationGuard();
    api.on('agent_turn_prepare', (event, ctx) => guard.prepare(event, ctx));
    api.on('before_tool_call', (event, ctx) => guard.before(event, ctx));
    api.on('after_tool_call', (event, ctx) => guard.after(event, ctx));
    api.on('agent_end', async (event, ctx) => {
      try { await deliver(api, extract(event, ctx)); } finally { guard.end(ctx); }
    });
    api.on('message_sent', (event, ctx) => deliver(api, extractSent(event, ctx)));
    api.on('after_tool_call', (event, ctx) => deliver(api, extractTool(event, ctx)));
  }
};
