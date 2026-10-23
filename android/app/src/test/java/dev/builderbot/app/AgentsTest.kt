// How the app names and finds a coding agent's session (Agents.kt), held to
// the dashboard's own rules: agents.session_name, names.running_session and
// the page's launchClaude and launchAgent arguments.
package dev.builderbot.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class AgentsTest {
    @Test fun liveAgentsAreTheTablesClaudeFirst() {
        assertEquals(listOf("claude", "codex", "copilot"), Agents.LIVE.map { it.id })
        assertEquals("ChatGPT", Agents.byId("codex")?.name)
        assertNull(Agents.byId("open"))
    }

    @Test fun sessionNamesAreTmuxSpelled() {
        assertEquals("claude-alpha", Agents.sessionName("claude", "alpha"))
        assertEquals("codex-example_com", Agents.sessionName("codex", "example.com"))
        assertEquals("copilot-a_b", Agents.sessionName("copilot", "a:b"))
        // An unknown agent is Claude's, as agents.session_name falls back.
        assertEquals("claude-x", Agents.sessionName("nope", "x"))
    }

    @Test fun aSessionNameIsReadBackAsItsAgent() {
        assertEquals("codex" to "web", Agents.ofSession("codex-web")?.let { it.first.id to it.second })
        assertEquals("copilot" to "web", Agents.ofName("u_1234abcd~copilot-web")?.let { it.first.id to it.second })
        assertNull(Agents.ofSession("shell-web-1"))
        assertNull(Agents.ofSession("codex-"))
    }

    @Test fun anyAgentsSessionIsFoundClaudesFirst() {
        val running = setOf("u_1234abcd~copilot-web", "u_1234abcd~claude-web", "u_1234abcd~codex-other")
        val got = Agents.runningOn("u_1234abcd~", "web", running).map { it.first.id }
        assertEquals(listOf("claude", "copilot"), got)
        assertEquals(listOf("codex"), Agents.runningOn("u_1234abcd~", "other", running).map { it.first.id })
        assertEquals(emptyList<String>(), Agents.runningOn("", "web", running).map { it.first.id })
    }

    @Test fun theTerminalArgumentIsThePages() {
        assertEquals("claude:alpha", Agents.termArg("claude", "alpha"))
        assertEquals("claude:alpha:r:abc:n:n_1", Agents.termArg("claude", "alpha", resume = "abc", model = "opus", node = "n_1"))
        assertEquals("codex:alpha:m:gpt-5.5:e:high", Agents.termArg("codex", "alpha", model = "gpt-5.5", effort = "high"))
        assertEquals("copilot:alpha:r:s1:n:n_2", Agents.termArg("copilot", "alpha", resume = "s1", node = "n_2"))
    }

    @Test fun startOffersWhatTheNodeHasTheDefaultFirst() {
        assertEquals(listOf("claude"), Agents.offered(emptyList(), emptyList(), "claude").map { it.id })
        assertEquals(listOf("copilot", "claude", "codex"),
                     Agents.offered(listOf("codex", "copilot"), emptyList(), "copilot").map { it.id })
        assertEquals(listOf("claude", "copilot"),
                     Agents.offered(listOf("codex", "copilot"), listOf("codex"), "claude").map { it.id })
    }

    @Test fun eachAgentsPrefsKeys() {
        assertEquals("model" to "effort", Agents.CLAUDE.let { it.modelKey to it.effortKey })
        assertEquals("codex_model" to "codex_effort", Agents.byId("codex")!!.let { it.modelKey to it.effortKey })
    }
}
