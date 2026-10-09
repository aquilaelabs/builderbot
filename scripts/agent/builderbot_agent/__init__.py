"""BuilderBot's node agent: one file, standard library only, dialing OUT.

A node runs this under systemd. It enrolls once with a token the operator
minted on the Nodes tab, then loops for the life of the machine: say hello,
ask for work, run what it is given, report what happened. The controller
never connects to a node (a node needs no open port, no inbound rule and no
key the controller could lose), and the credential it holds opens nothing
but its own row (docs/nodes.md §4, §8).

The protocol is six verbs over plain HTTP, and this file speaks four of them
plus the download that fetches itself:

    POST /api/v1/agent/enroll     once: the enroll token in, the node token out
    POST /api/v1/agent/hello      on connect and every ten minutes: the census,
                                  and the ids of the jobs still running here
    POST /api/v1/agent/work       the long-poll: a heartbeat sample in, a job
                                  (or 204, or {"cancel": [ids]}) out, held up
                                  to `poll` seconds
    POST /api/v1/agent/log        chunks of a running job's output, by sequence;
                                  the reply carries `cancel: true` once the
                                  operator has stopped that job
    POST /api/v1/agent/result     the terminal state (succeeded, failed,
                                  canceled), exit code and a one-line error
    GET  /api/v1/agent/download   the agent the controller ships, for self-update

Three rules this file keeps that are worth knowing before changing it:

  * The agent is the DURABLE side of a job (door 5). A controller restart
    must never kill running work: log chunks that could not be posted are
    kept and re-sent by sequence number, the result is retried until it is
    acknowledged, and a job started before the controller went away finishes
    and reports late.
  * The node enforces its own capabilities (door 7). A job that requires a
    capability this node was not enrolled with is refused HERE, whatever the
    controller's row says. The row is a claim, the enrollment is the fact.
  * Jobs never run as root. The unit runs the agent as root so that phase 5's
    system jobs (mounts, network) can, but an exec job drops to the account
    the provisioner enrolled (the same `bb` that docker runs as) before it
    runs anything. A session that reaches this box through a job has the
    reach it already had over ssh, and no more.
  * Sessions run here too (roadmap #24), and as a THIRD account. Beside the
    jobs this keeps two ttyds up, the same two the controller's dashboard
    hook starts, running bb-tty from the bb bundle the controller ships,
    so a Claude session on this node's projects lives on this node, with
    this node's toolchains and the projects share it mounts. They run as
    the session account the provisioner made (--session-user), which is in
    no docker group: docker is root on any machine with a daemon, and the
    account a session works as is the one thing here to keep away from it.

Runs anywhere Python 3.8+ is, with nothing installed:

    builderbot-agent enroll --controller URL --token bbe_… [--user bb]
                            [--session-user builder] [--store data=/path]
                            [--pin sha256:…]
    builderbot-agent run            # the loop; what the unit runs
    builderbot-agent status         # what this node is, and does it answer
"""

# WINDOW.BUILD, and the two halves answer different questions.
#
# The WINDOW is the project's semver minor, and it is the compatibility
# promise: while BuilderBot is 0.4.x, any 0.4 agent works with any 0.4
# controller and the other way round. 0.5.0 is where that promise ends and
# where breaking changes and the removal of stale compatibility paths belong.
# A test holds this half to the VERSION file, so the two cannot drift apart
# quietly; see test/agent.mjs.
#
# The BUILD is the agent's own counter and moves only when the agent moves,
# which is why it is not BuilderBot's patch number: most patches ship no new
# agent. It does NOT reset at a window boundary (0.5.28 follows 0.4.27), so
# that "which of these two is newer" always has an answer. A reset would put
# the same number on two different agents, and a number that cannot say which
# is newer is the reason the flat protocol number this replaced was useless.
AGENT_VERSION = "0.7.153"
