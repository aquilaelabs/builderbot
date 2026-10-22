"""What a session's hooks have to say, from a NODE (roadmap #24).

bb-work-note and bb-prompt-relay write this container's /config when they
run here: the overlap notes, the project's chat feed. On a node there is no
/config, so they post the same things to /api/v1/hook with the session's
token, and the same modules write them: `note` (a file the session is about
to edit, with a guess at the symbol; answers who else has it open), `asked`
(what the person typed, into the project feed), `started` (the session
began, and this is the only place that is announced from, since every
session is on a node), `seen` (what the notebook has done since this
session was last told; the answer goes back into the turn the hook is
already in, which is how a session stays current without anybody pressing
a button, roadmap #27), and `turn` and `turn-done` (a prompt about to
start, or a turn over: turns.py).

The house rules ride on the same round trips (R200, B686): a `note`'s
answer carries the named rules the file fires and a `seen`'s the ones the
prompt fires, said whole, with their names so the session's hook can
remember what fired; `guards` is what the Bash guard refuses here; and
`recall` says again, after a summary, the rules a conversation was told.

The account is the token's, never the request's: the server checks the
token and hands verb() the account and project it was minted for, and
that is who the note is filed under and who the feed says asked.
"""
import agents
from fields import field

# The server's, handed over by configure(): the account store, the overlap
# notes, the chat feed, the notebook's catch-up and what it had waiting, the
# turn queue and the node registry, and two of the server's own: what a
# session is told it has not seen (session_seen_note) and which node and
# limit its turns count against (turn_scope).
users = None
rules = None
preamble = None
overlap = None
chat = None
roadmap = None
pending = None
turns = None
nodes = None
seen_note = None
agent_state = None     # (project, uid, agent, state): another agent's working or waiting
turn_scope = None
# server.asking_set and asking_clear: a session on its permission prompt (B52).
asking_set = None
asking_clear = None
asked = None          # projsessions.asked: what a session was last asked (B59)


def configure(**deps):
    globals().update(deps)


def verb(kind, req, me, uid, project):
    """One hook's word for the session `me` names, running as `uid` on
    `project`. (payload, status)."""
    store = users.load()["users"]
    name = next((n for n, u in store.items() if u.get("uid") == uid), "") or uid
    # Which coding agent's session spoke (R95 step 7): its hooks say so,
    # Claude's when they do not.
    ag = agents.get(req.get("agent")) if isinstance(req, dict) else None
    agent = ag.id if ag and ag.live else "claude"
    if kind == "note":
        path = str(req.get("path") or "")[:400]
        if not path:
            return {"error": "a note names a file"}, 400
        # Keyed by account and agent (R95): a person's Codex session is told
        # of their own Claude session's edits, and named for its agent.
        me_key = overlap.key(uid, agent)
        others = overlap.others_touching(project, me_key, path)
        overlap.note(project, me_key, path, str(req.get("symbol") or "")[:120])
        by_uid = {u.get("uid"): n for n, u in store.items() if u.get("uid")}
        told = set(req.get("told") or []) if isinstance(req.get("told"), list) else set()
        hit = [r for r in rules.matching(project, path=path) if r["name"] not in told]
        return {"ok": True, "others": [overlap.said(o, by_uid) for o in others],
                "rules": rules.said(hit, path=path), "names": [r["name"] for r in hit]}, 200
    if kind == "asked":
        text = str(req.get("text") or "").strip()[:800]
        if not text:
            return {"error": "nothing asked"}, 400
        chat.post(project, uid, f"{name} asked: {text}", kind="asked")
        return {"ok": True}, 200
    if kind == "started":
        chat.event(project, uid, f"{name} started a {agents.get(agent).name} session on {project}"
                                 + (f" ({field(req, 'node')})" if field(req, "node") else ""))
        seen_note(project, uid, field(req, "node"), who=me, begin=True)
        return {"ok": True}, 200
    if kind in ("seen", "turn-done") and asking_clear is not None:
        asking_clear(project, uid, agent)
    if kind == "seen":
        # What this session has not been told about the notebook, and
        # marked told (roadmap #27). The answer rides back into the turn
        # the hook is already in, so nothing is spent on saying it.
        # ...and what the operator decided about anything it had waiting
        # for approval, which is the other half of #27.
        line = " ".join(x for x in (roadmap.catchup(project, uid),
                                    pending.settled_line(project),
                                    seen_note(project, uid, field(req, "node"), who=me)) if x)
        # ...and the rules the prompt raises, on the trip already being made.
        # ...less the ones this conversation was told already (`told`):
        # each named rule is said once a conversation, and again only
        # after a summary (recall), not on every prompt that names it.
        told = set(req.get("told") or []) if isinstance(req.get("told"), list) else set()
        prompt = str(req.get("prompt") or "")[:20000]
        # ...and what it was asked, for its row's task (B59).
        if asked:
            asked(uid, project, prompt)
        hit = [r for r in rules.matching(project, prompt=prompt) if r["name"] not in told]
        # ...and the open items and bugs the prompt names (R202), the same way.
        related, rnames = preamble.mentioned(project, prompt, told)
        return {"ok": True, "line": line, "rules": rules.said(hit), "related": related,
                "names": [r["name"] for r in hit] + rnames}, 200
    if kind == "asking":
        # Claude Code waits on its own permission prompt (B52): marked until
        # it works again, its turn ends or it is sent a prompt.
        if asking_set is not None:
            asking_set(project, uid, str(req.get("text") or ""), agent)
        return {"ok": True}, 200
    if kind == "guards":
        return {"ok": True, "guards": rules.guards(project)}, 200
    if kind == "recall":
        names = req.get("names") if isinstance(req.get("names"), list) else []
        return {"ok": True, "rules": rules.said(rules.by_names(project, names[:200]), again=True)}, 200
    if kind in ("turn", "turn-done"):
        # A prompt about to start, or a turn over (turns.py): how many
        # sessions on one node work at once, when an administrator has
        # said. No node to count on, or no limit, and every turn goes.
        # Another agent's session says working and waiting by its turns,
        # which is all it has to say it with (R95 step 7).
        if agent_state is not None and agent != "claude":
            agent_state(project, uid, agent, "working" if kind == "turn" else "waiting")
        scope = turn_scope(project, uid, agent)
        if not scope:
            return {"ok": True, "go": True}, 200
        nid, key, limit, heart, at = scope
        if kind == "turn-done":
            turns.done(nid, key)
            return {"ok": True}, 200
        r = turns.ask(nid, key, limit, heart, at)
        if not r["go"]:
            n = nodes.node(nid) or {}
            r["node"] = n.get("name") or nid
        return {"ok": True, **r}, 200
    return {"error": "a hook is note, asked, started, seen, asking, guards, recall, turn or turn-done"}, 400
