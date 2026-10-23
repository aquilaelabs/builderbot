// The coding agents a session may run (R95), as the app reads them: the
// live rows of the dashboard's table (scripts/dashboard/agents.py, whose
// page copy is page-agents.js), and the names their sessions and terminals
// go by. A session used to be Claude's by construction, so the app found
// yours only as prefix + claude-PROJECT; a ChatGPT or Copilot session had
// no pill, no Say box and no note. Every place that asks "is mine running"
// asks here now, by the agent-neutral rule names.py's running_session
// keeps: any live agent's, Claude's first.
//
// Plain Kotlin with no Android in it, so the unit tests read it as it is.
package dev.builderbot.app

/** One coding agent: its table key, the name a person reads, the program,
 *  and the models and efforts Start's step offers for it. Claude's are the
 *  project settings' own (prefs.MODELS, prefs.EFFORTS) and are saved as
 *  `model` and `effort`; another agent's ride its terminal argument and are
 *  saved as `ID_model` and `ID_effort` (R95 step 9). */
data class Agent(val id: String, val name: String, val product: String,
                 val models: List<String> = emptyList(), val efforts: List<String> = emptyList()) {
    /** The /api/prefs keys its model and effort are kept under. */
    val modelKey get() = if (id == "claude") "model" else "${id}_model"
    val effortKey get() = if (id == "claude") "effort" else "${id}_effort"
}

object Agents {
    private val EFFORTS = listOf("low", "medium", "high", "xhigh", "max")

    /** Live and wired end to end, Claude first. agents.py's MODELS and
     *  EFFORTS for the other two, read off the same table the page copies. */
    val LIVE = listOf(
        Agent("claude", "Claude", "Claude Code",
              listOf("opus", "sonnet", "haiku", "fable"), EFFORTS),
        Agent("codex", "ChatGPT", "Codex CLI",
              listOf("gpt-6.1-sol", "gpt-6-sol", "gpt-6-astra", "gpt-6-luna", "gpt-5.6-sol",
                     "gpt-5.6-terra", "gpt-5.6-luna", "gpt-5.5"), EFFORTS),
        Agent("copilot", "Copilot", "Copilot CLI",
              listOf("auto", "claude-sonnet-5.5", "claude-opus-5.5", "claude-haiku-5.5", "gpt-6.1-sol",
                     "gpt-6-sol", "gpt-5.6-sol", "gpt-5-mini", "gemini-4-argon", "gemini-3.8-flash",
                     "grok-4.7"), EFFORTS),
    )

    fun byId(id: String?): Agent? = LIVE.firstOrNull { it.id == id }
    val CLAUDE get() = LIVE[0]

    /** What tmux will call a session asked for under this name: it rewrites
     *  `.` and `:` to `_` and says nothing (names.tmux_name). */
    fun tmuxName(s: String) = s.replace(Regex("[.:]"), "_")

    /** The session an agent's conversation on a project runs in, before the
     *  account prefix (agents.session_name): `codex-PROJECT`. */
    fun sessionName(agentId: String, project: String) = tmuxName("${(byId(agentId) ?: CLAUDE).id}-$project")

    /** (agent, stem) for a session name with its account prefix off, or
     *  null for a shell or anything else (agents.of_session). */
    fun ofSession(base: String): Pair<Agent, String>? = LIVE.firstNotNullOfOrNull { a ->
        if (base.startsWith(a.id + "-") && base.length > a.id.length + 1) a to base.substring(a.id.length + 1) else null
    }

    /** The same for a full name, an account's prefix (`u_1234abcd~`) and
     *  all, as a roadmap's `session` or a status row names it. */
    fun ofName(name: String): Pair<Agent, String>? = ofSession(name.replace(Regex("^u_[0-9a-f]{8}~"), ""))

    /** This account's session names on a project, one per live agent,
     *  Claude's first: what a look for "mine" has to try. */
    fun ownNames(prefix: String, project: String): List<Pair<Agent, String>> =
        LIVE.map { it to prefix + sessionName(it.id, project) }

    /** Which of this account's agents has a session running on the project,
     *  in the table's order (names.running_session): `running` is the set
     *  of full session names the status lists. */
    fun runningOn(prefix: String, project: String, running: Set<String>): List<Pair<Agent, String>> =
        ownNames(prefix, project).filter { it.second in running }

    /** The terminal argument that opens (and so starts) an agent's session
     *  on a project, as the page's launchClaude and launchAgent build it:
     *  `codex:PROJECT`, then `:r:ID` to resume a conversation, `:m:` and
     *  `:e:` for another agent's model and effort (bb-tty holds them to its
     *  own lists; Claude's are saved to the project instead), and `:n:NODE`
     *  where the project runs on several nodes. */
    fun termArg(agentId: String, project: String, resume: String = "", model: String = "",
                effort: String = "", node: String = ""): String {
        val a = byId(agentId) ?: CLAUDE
        val me = if (a.id == "claude") "" else
            (if (model.isNotBlank()) ":m:$model" else "") + (if (effort.isNotBlank()) ":e:$effort" else "")
        return "${a.id}:$project" + (if (resume.isNotBlank()) ":r:$resume" else "") + me +
            (if (node.isNotBlank()) ":n:$node" else "")
    }

    /** The agents a project's Start offers on one node, its default first:
     *  Claude always, another where the node has it installed (`installed`,
     *  the node row's `agents`) and the project has not switched it off. */
    fun offered(installed: List<String>, off: List<String>, first: String): List<Agent> =
        LIVE.filter { (it.id == "claude" || it.id in installed) && it.id !in off }
            .sortedBy { if (it.id == first) 0 else 1 }
}
