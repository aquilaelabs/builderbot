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
  {id: "open", name: "Any model", product: "OpenCode", command: "opencode", provider: "", live: false},
];

// ---- reading names ----
// The agents a session may run today, Claude first.
function agentsLive(){ return AGENTS.filter(a => a.live); }
function agentById(id){ return AGENTS.find(a => a.id === id) || null; }
// {agent, stem} for a session name with its account prefix already off
// (`claude-alpha`), or null for a shell or anything else.
function agentOfSession(base){
  const b = String(base ?? "");
  for (const a of agentsLive())
    if (b.startsWith(a.id + "-") && b.length > a.id.length + 1) return {agent: a, stem: b.slice(a.id.length + 1)};
  return null;
}
// {agent, project, rest} for a terminal argument (`claude:alpha:r:UUID`), or
// null for any other.
function agentOfArg(arg){
  const s = String(arg ?? "");
  for (const a of agentsLive())
    if (s.startsWith(a.id + ":")){
      const rest = s.slice(a.id.length + 1);
      return {agent: a, project: rest.split(":")[0], rest};
    }
  return null;
}
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
