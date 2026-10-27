const raw = process.env.AI_COWORKER_AGENTS || 'reviewer,researcher,operator';
export const PARTICIPANTS = new Set(raw.split(',').map(x => x.trim()).filter(Boolean));
if (!PARTICIPANTS.size || [...PARTICIPANTS].some(x => !/^[a-z][a-z0-9_-]{0,47}$/.test(x))) {
  throw new Error('AI_COWORKER_AGENTS must contain explicit valid agent IDs');
}
export function hardwareSession(session) {
  const match = /^agent:([a-z][a-z0-9_-]{0,47}):openai-user:.+$/.exec(session || '');
  return !!match && PARTICIPANTS.has(match[1]);
}
