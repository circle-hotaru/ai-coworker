// Local policy for Reviewer/Operator/Researcher peer requests. OpenClaw owns the one-shot reply flow.
import {PARTICIPANTS} from './settings.js';
const EXPIRY_MS = 30 * 60 * 1000;
function normalized(value) { return typeof value === 'string' ? value.trim().toLowerCase() : ''; }
function textOf(message) {
  if (typeof message?.content === 'string') return message.content;
  return Array.isArray(message?.content) ? message.content.filter(p => p?.type === 'text').map(p => p.text).join('\n') : '';
}
function sourceOf(event) {
  const prompt = typeof event.prompt === 'string' ? event.prompt.trimStart() : '';
  const latestUser = [...(event.messages || [])].reverse().find(m => m?.role === 'user');
  // Prefer the current prompt; never infer a peer request from old history when
  // this turn has a direct human prompt.
  const userText = textOf(latestUser).trim();
  const current = prompt || userText;
  const match = /^\[Inter-session message\]\s+sourceSession=(\S+)[^\n]*\bsourceTool=sessions_send\b/.exec(current);
  if (match) return normalized(match[1]);
  const provenance = latestUser?.provenance;
  const matchesCurrent = userText && (!prompt || prompt.includes(userText) || userText.endsWith(prompt));
  if (matchesCurrent && provenance?.kind === 'inter_session' && provenance.sourceTool === 'sessions_send') {
    return normalized(provenance.sourceSessionKey) || null;
  }
  return null;
}
function signature(params) {
  const target = normalized(params?.sessionKey);
  const message = typeof params?.message === 'string' ? params.message.trim().replace(/\s+/g, ' ') : '';
  return target && message ? JSON.stringify([target, message]) : null;
}
function resultDetails(result) {
  if (result?.isError) return null;
  if (result?.details && typeof result.details === 'object') return result.details;
  for (const item of result?.content || []) {
    if (item.type !== 'text') continue;
    try { return JSON.parse(item.text); } catch { /* ordinary text is not a receipt */ }
  }
  return null;
}
export class CollaborationGuard {
  constructor(now = () => Date.now()) { this.now = now; this.runs = new Map(); this.sessions = new Map(); }
  get(ctx) {
    const direct = ctx.runId && this.runs.get(ctx.runId);
    const state = direct || this.sessions.get(normalized(ctx.sessionKey));
    if (!state || this.now() - state.updated > EXPIRY_MS) return null;
    // Never reuse another run's peer classification for a new turn.
    if (ctx.runId && state.runId && ctx.runId !== state.runId) return null;
    return state;
  }
  prepare(event, ctx) {
    if (!PARTICIPANTS.has(ctx.agentId) || !ctx.sessionKey) return;
    for (const [run, state] of this.runs) if (this.now()-state.updated>EXPIRY_MS) this.runs.delete(run);
    for (const [session, state] of this.sessions) if (this.now()-state.updated>EXPIRY_MS) this.sessions.delete(session);
    const state = {source:sourceOf(event), runId:ctx.runId, session:normalized(ctx.sessionKey), accepted:new Set(), updated:this.now()};
    if (ctx.runId) this.runs.set(ctx.runId, state);
    this.sessions.set(state.session, state);
    return {appendContext: state.source
      ? `协作去重规则：本轮是 ${state.source} 经 sessions_send 发来的消息。请在本轮最终答复中给出一次结果或澄清问题；OpenClaw 会自动把最终答复交回请求方。不得再用 sessions_send 向 ${state.source} 发送同一结果，也不把咨询答复、转述或确认当成新的咨询。若系统明确本轮是先前咨询的完成通知，只向当前用户转达一次，不再回传目标 Agent。`
      : '协作去重规则：用户要求联系同事时，每个相同咨询只调用一次 sessions_send；accepted/queued 表示已受理，不是失败，不重复发送，也不要为普通 peer sessions_send 调用 sessions_yield。当后续完成通知到达，向用户转达一次即可，等待真正的新问题。'};
  }
  before(event, ctx) {
    if (!PARTICIPANTS.has(ctx.agentId) || event.toolName !== 'sessions_send') return;
    const state = this.get(ctx); if (!state) return;
    const target = normalized(event.params?.sessionKey);
    if (state.source && target === state.source) {
      return {block:true, blockReason:'本轮已经属于该来源会话的咨询/完成回传。OpenClaw 会自动回传最终答复；不要再 sessions_send 回同一来源。请直接在最终答复里返回结果或澄清问题，避免启动第二条咨询和重复播报。'};
    }
    const key = signature(event.params);
    if (key && state.accepted.has(key)) return {block:true, blockReason:'同一咨询在本轮已经被 OpenClaw 受理。请使用既有请求的结果或等待完成通知，不要重复发送。'};
  }
  after(event, ctx) {
    if (!PARTICIPANTS.has(ctx.agentId) || event.toolName !== 'sessions_send' || event.error) return;
    const state = this.get(ctx); if (!state) return;
    const details = resultDetails(event.result);
    if (!details || !['accepted','ok'].includes(details.status)) return;
    const key = signature(event.params); if (key) state.accepted.add(key);
  }
  end(ctx) {
    const state = this.get(ctx); if (!state) return;
    if (state.runId) this.runs.delete(state.runId);
    if (this.sessions.get(state.session) === state) this.sessions.delete(state.session);
  }
}
