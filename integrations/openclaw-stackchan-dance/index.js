const allowedAgent = process.env.AI_COWORKER_DANCE_AGENT || 'operator';
if (!/^[a-z][a-z0-9_-]{0,47}$/.test(allowedAgent)) throw new Error('Invalid motion agent');
export default {
  id: "stackchan-dance",
  name: "Operator StackChan Dance",
  register(api) {
    for (const action of ["start", "stop", "status"]) {
      const name = `stackchan_dance_${action}`;
      api.registerTool((ctx) => {
        if (ctx.agentId !== allowedAgent) return null;
        return {
          name,
          label: `Operator dance.${action}`,
          description: {
            start: "Start Operator hardware's single fixed six-second hello dance (dance.start). Requires an explicit user request to dance. Returns actual firmware state, not a promise. Never claim success on error. No music in this motion-only preset.",
            stop: "Stop Operator hardware dance (dance.stop): cancels remaining steps, gently returns to rest and releases torque. User requests to stop should call this immediately.",
            status: "Read actual Operator dance state (dance.status): ready, idle, dancing, returning or fault. Use to verify completion rather than assuming it."
          }[action],
          parameters: {type:"object",properties:action === "start" ? {preset:{type:"string",enum:["hello"],description:"The only installed preset; omit or use hello."}} : {},additionalProperties:false},
          async execute() {
            try {
              const response = await fetch(`http://127.0.0.1:8003/xiaozhi/dance/${action}`, {method:"POST", signal:AbortSignal.timeout(5000), redirect:"error"});
              const details = await response.json();
              return {content:[{type:"text",text:JSON.stringify(details)}],details,isError:!response.ok};
            } catch (error) {
              return {content:[{type:"text",text:`Operator motion bridge unavailable: ${error.message}`}],isError:true};
            }
          }
        };
      }, {name});
    }
  }
};
