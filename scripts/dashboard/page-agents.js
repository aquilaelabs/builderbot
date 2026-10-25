"use strict";
// The coding agents a session may run (R95): the page's copy of agents.py's
// table, which unit/test_agents.py holds to the server's. A place on the page
// that used to say claude asks here which agent a session name or a
// terminal argument is, so a second agent is one row, not a hunt. A row whose
// `live` is false is planned and not wired: no name is read as its and no
// Start offers it.

// ---- the table ----
const AGENTS = [
  {id: "claude", name: "Claude", product: "Claude Code", command: "claude", provider: "Anthropic", live: true},
  {id: "codex", name: "ChatGPT", product: "Codex CLI", command: "codex", provider: "OpenAI", live: true},
  {id: "copilot", name: "Copilot", product: "Copilot CLI", command: "copilot", provider: "GitHub", live: true},
  {id: "grok", name: "Grok", product: "Grok Build", command: "grok", provider: "xAI", live: true},
  {id: "open", name: "Any model", product: "OpenCode", command: "opencode", provider: "", live: false},
];

// Each agent's own models and efforts beside Claude's (agents.py MODELS,
// EFFORTS; R95 step 9), what Start's model and effort step offers for it.
const AGENT_MODELS = {
  codex: {models: ["gpt-6.1-sol", "gpt-6-sol", "gpt-6-astra", "gpt-6-luna", "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna", "gpt-5.5"],
          efforts: ["low", "medium", "high", "xhigh", "max"]},
  copilot: {models: ["auto", "claude-sonnet-5.5", "claude-opus-5.5", "claude-haiku-5.5", "gpt-6.1-sol", "gpt-6-sol", "gpt-5.6-sol", "gpt-5-mini", "gemini-4-argon", "gemini-3.8-flash", "grok-4.7"],
            efforts: ["low", "medium", "high", "xhigh", "max"]},
};

// Which of BuilderBot's guards hold for each agent, and through what (R95
// step 6), as a project's settings say it rather than implying parity.
const AGENT_GUARDS = {
  claude: "every guard, through Claude Code's own hooks: the hold while BuilderBot updates, the node's turn limit, the house rules' command guard and their recall after a summary, the work note, the prompt relay, the stop check and the asking mark",
  codex: "the same guards through Codex's own hooks (before a tool, a prompt, the stop, its permission prompt and after a summary), but for the code map's hint before a search, which it has no tool for",
  copilot: "the same guards through Copilot's own hooks (before a tool, a prompt, the stop and its permission prompt), but for the house rules' recall after a summary, which it has no hook for, and the code map's hint",
  grok: "the same guards through Grok's own hooks (before a tool, a prompt, the stop and after a summary), but for the asking mark, which it has no permission-prompt hook for, and a house rule's words on a prompt, which it does not pass on to the model",
};

// ---- reading names ----
// The agents a session may run today, Claude first.
function agentsLive(){ return AGENTS.filter(a => a.live); }
function agentById(id){ return AGENTS.find(a => a.id === id) || null; }
// Who an account is signed in as with each agent, in the agents' order, as
// "Claude: a@x · ChatGPT: b@y", from a record's agents ({id: emails}), with
// Claude's own field for a server that sends only it; "" for none (B296).
function agentLogins(rec){
  const by = {...(rec?.claude ? {claude: rec.claude} : {}), ...(rec?.agents || {})};
  return AGENTS.filter(a => by[a.id]).map(a => `${esc(a.name)}: ${esc(by[a.id])}`).join(" · ");
}
// The most sessions of one agent a person may have on one project, and the
// mark a second one's name carries (agents.py MAX_SLOTS, SLOT_SEP; R143).
const AGENT_MAX_SLOTS = 9;
// {agent, stem, slot} for a session name with its account prefix already
// off (`claude-alpha`, `claude-alpha~2` its second slot, R143), or null for
// a shell or anything else. The stem is the project's tmux name in either.
function agentOfSession(base){
  const b = String(base ?? "");
  for (const a of agentsLive())
    if (b.startsWith(a.id + "-") && b.length > a.id.length + 1){
      const tail = b.slice(a.id.length + 1), m = tail.match(/~([2-9])$/);
      const stem = m ? tail.slice(0, -m[0].length) : tail;
      return stem ? {agent: a, stem, slot: m ? +m[1] : 1} : null;
    }
  return null;
}
// {agent, project, slot, rest} for a terminal argument
// (`claude:alpha:r:UUID`, `claude:alpha:s:2`), or null for any other.
function agentOfArg(arg){
  const s = String(arg ?? "");
  for (const a of agentsLive())
    if (s.startsWith(a.id + ":")){
      const rest = s.slice(a.id.length + 1), m = rest.match(/:s:([1-9])(?::|$)/);
      return {agent: a, project: rest.split(":")[0], slot: m ? +m[1] : 1, rest};
    }
  return null;
}
// The session an agent's slot on a project runs in, before the account's
// prefix (agents.session_name): `claude-alpha`, `claude-alpha~2`.
function agentSessionName(id, project, slot = 1){
  return `${(agentById(id) || AGENTS[0]).id}-${tmuxName(project)}${slot > 1 ? `~${slot}` : ""}`;
}
// A coding agent's session as a person says it: "ChatGPT on web", by the
// agent its name carries and the project's own name, never the tmux one.
function agentSessionWords(name){
  const b = tmuxBase(name), at = agentOfSession(b);
  if (!at) return b;
  return `${agentSlotName(at.agent, at.slot)} on ${projLabel(projFor(at.stem) ?? at.stem)}`;
}
// An agent's slot as a person reads it (R143): "Claude", then "Claude 2".
const agentSlotName = (a, slot = 1) => `${a?.name || "Claude"}${slot > 1 ? ` ${slot}` : ""}`;
// What a count of agent sessions is called: the one agent's name when they
// are all one agent's ("2 of them Claude"), else "coding agents".
function agentsWord(names){
  const ids = new Set(names.map(n => agentOfSession(tmuxBase(n))?.agent.id).filter(Boolean));
  return ids.size === 1 ? agentById([...ids][0]).name : "coding agents";
}
// Who a record says asked, when it was a session ("claude", the stored word
// for any session's): the agent it names (R95), or Claude, whose sessions
// were the only ones before a record named its agent.
function agentAsker(rec){ return agentById(rec?.agent)?.name || "Claude"; }
// The argument that opens an agent's session on a project: `claude:alpha`.
function agentArg(id, project){ return `${(agentById(id) || AGENTS[0]).id}:${project}`; }
// ...and its slot's (R143), which bb-tty reads by suffix before the boot, so
// it goes after a resume, a model and an effort, and before a node.
const slotArg = slot => slot > 1 ? `:s:${slot}` : "";
