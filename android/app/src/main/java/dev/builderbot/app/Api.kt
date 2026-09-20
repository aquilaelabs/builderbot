// The dashboard's API, as the app speaks it: Basic auth on every request
// (the same credential the browser sends), JSON in and out, one place that
// knows the server's address. Kept to the platform's own HTTP client and
// org.json so the app carries no networking stack of its own. The surface
// it calls is small, and android/api-surface.json names every path here.
package dev.builderbot.app

import android.util.Base64
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL

class ApiError(val status: Int, message: String) : IOException(message)

class Api(private val base: String, private val user: String, private val password: String) {

    private fun open(path: String, method: String): HttpURLConnection {
        val url = URL(base.trimEnd('/') + path)
        val c = url.openConnection() as HttpURLConnection
        c.requestMethod = method
        c.connectTimeout = 15_000
        c.readTimeout = 60_000
        c.instanceFollowRedirects = false
        val cred = Base64.encodeToString("$user:$password".toByteArray(), Base64.NO_WRAP)
        c.setRequestProperty("Authorization", "Basic $cred")
        c.setRequestProperty("Accept", "application/json")
        c.setRequestProperty("User-Agent", "BuilderBot-app/${BuildConfig.VERSION_NAME} api/${BuildConfig.TARGET_API}")
        return c
    }

    private fun readJson(c: HttpURLConnection): JSONObject {
        val status = c.responseCode
        val stream = if (status < 400) c.inputStream else c.errorStream
        val text = stream?.bufferedReader()?.use { it.readText() } ?: ""
        val obj = try { JSONObject(text) } catch (e: Exception) { JSONObject() }
        if (status >= 400) {
            throw ApiError(status, obj.optString("error").ifBlank { "HTTP $status" })
        }
        return obj
    }

    suspend fun get(path: String): JSONObject = withContext(Dispatchers.IO) {
        val c = open(path, "GET")
        try { readJson(c) } finally { c.disconnect() }
    }

    suspend fun post(path: String, body: JSONObject): JSONObject = withContext(Dispatchers.IO) {
        val c = open(path, "POST")
        c.doOutput = true
        c.setRequestProperty("Content-Type", "application/json")
        try {
            c.outputStream.use { it.write(body.toString().toByteArray()) }
            readJson(c)
        } finally { c.disconnect() }
    }

    // ---- the surface, one function per path the app uses -------------------
    suspend fun status() = get("/api/status")
    suspend fun meta() = get("/api/meta")
    suspend fun phone() = get("/api/phone")
    suspend fun decide(id: Int, allow: Boolean) =
        post("/api/phone", json("action" to (if (allow) "allow" else "deny"), "id" to id))
    suspend fun pending(project: String) = get("/api/pending?project=${enc(project)}")
    suspend fun pendingAct(project: String, allow: Boolean, ids: List<String>) =
        post("/api/pending", json("project" to project, "action" to (if (allow) "approve" else "deny"),
                                  "ids" to JSONArray(ids)))
    suspend fun roadmap(project: String) = get("/api/roadmap?project=${enc(project)}")
    suspend fun roadmapAdd(project: String, text: String) =
        post("/api/roadmap", json("project" to project, "action" to "add", "text" to text))
    suspend fun roadmapShelve(project: String, id: Any) =
        post("/api/roadmap", json("project" to project, "action" to "shelve", "id" to id))
    suspend fun roadmapRemove(project: String, id: Any, why: String) =
        post("/api/roadmap", json("project" to project, "action" to "remove", "id" to id, "why" to why))
    // A step, into the session's own input. `step` null means the next one
    // that has not gone, which is what the panel sends and what somebody on a
    // phone means by "send the next bit". The answer says whether the line
    // actually landed: a step is marked sent only when it did.
    suspend fun roadmapSend(project: String, id: Any, step: Int?, note: String) =
        post("/api/roadmap", json("project" to project, "action" to "send", "id" to id,
                               "step" to step, "note" to note))
    suspend fun bugs(project: String) = get("/api/bugs?project=${enc(project)}")
    suspend fun bugAdd(project: String, title: String, severity: String, area: String, repro: String) =
        post("/api/bugs", json("project" to project, "action" to "add", "title" to title,
                               "severity" to severity, "area" to area, "repro" to repro))
    suspend fun bugStatus(project: String, id: Any, status: String, note: String) =
        post("/api/bugs", json("project" to project, "action" to "status", "id" to id,
                               "status" to status, "note" to note))
    // The number and an instruction to read it, never the report itself: the
    // tracker is the copy that stays current, and a paste starts going stale
    // the moment somebody adds a note to it.
    suspend fun bugSend(project: String, id: Any, note: String) =
        post("/api/bugs", json("project" to project, "action" to "send", "id" to id, "note" to note))
    suspend fun rules(project: String) = get("/api/rules?project=${enc(project)}")
    suspend fun memory(project: String) = get("/api/memory?project=${enc(project)}")
    suspend fun artifacts(project: String) = get("/api/artifacts?project=${enc(project)}")
    suspend fun git(project: String) = get("/api/git?project=${enc(project)}&what=status")
    suspend fun nodes() = get("/api/v1/nodes")
    suspend fun nodeAct(id: String, action: String) =
        post("/api/v1/nodes", json("action" to action, "id" to id))
    // The toolchain store, and what may be added to it. The listing is NOT
    // administrators-only: what a node carries decides whether a build can
    // run there, and that is everybody's question; installing is theirs.
    // `node` empty means the controller's own store, which is what the
    // dashboard's picker calls the first entry.
    suspend fun toolchains(node: String) =
        get("/api/toolchains" + if (node.isBlank()) "" else "?node=${enc(node)}")
    suspend fun toolchainAct(node: String, action: String, names: List<String>) =
        post("/api/toolchains", json("action" to action, "node" to node,
                                     "names" to JSONArray(names)))
    suspend fun users() = get("/api/users")
    /** One account, in one Save, using the same verb the dashboard's modal uses, so
     *  the owner protections that live in users.py hold here too. A blank
     *  password leaves the existing one alone. */
    suspend fun userEdit(name: String, role: String, projects: List<String>, password: String) =
        post("/api/users", json("action" to "edit", "name" to name, "role" to role,
                                "projects" to JSONArray(projects), "password" to password))
    suspend fun userAdd(name: String, password: String, role: String) =
        post("/api/users", json("action" to "add", "name" to name,
                                "password" to password, "role" to role))
    suspend fun userRemove(name: String) =
        post("/api/users", json("action" to "remove", "name" to name))
    suspend fun profile() = get("/api/profile")
    suspend fun profileSave(fields: Map<String, String>) =
        post("/api/profile", json("action" to "save", "profile" to JSONObject(fields)))
    suspend fun password(current: String, next: String) =
        post("/api/profile", json("action" to "password", "current" to current, "password" to next))
    suspend fun prefs(project: String, patch: Map<String, Any>) =
        post("/api/prefs", JSONObject(patch).put("project", project))

    /** An artifact's BYTES, into a file. The only call here that is not JSON:
     *  the newer APK is an artifact like any other, and installing it from the
     *  phone is the difference between an app that can update itself and one
     *  that needs a desktop to reach the same file. Streamed rather than read
     *  into memory: this is twelve megabytes. */
    suspend fun download(path: String, dest: java.io.File): java.io.File = withContext(Dispatchers.IO) {
        val c = open(path, "GET")
        c.setRequestProperty("Accept", "*/*")
        try {
            if (c.responseCode >= 400) {
                val said = c.errorStream?.bufferedReader()?.use { it.readText() } ?: ""
                throw ApiError(c.responseCode,
                    try { JSONObject(said).optString("error") } catch (e: Exception) { "" }
                        .ifBlank { "HTTP ${c.responseCode}" })
            }
            dest.outputStream().use { out -> c.inputStream.use { it.copyTo(out) } }
            dest
        } finally { c.disconnect() }
    }

    /** Where the companion APK is served from, given the bare filename
     *  /api/meta reports. BuilderBot's own dist/, which is the one project
     *  that builds this app. */
    fun apkPath(apk: String) =
        "/api/artifact?project=BuilderBot&path=" + enc("dist/$apk")

    companion object {
        fun enc(s: String) = java.net.URLEncoder.encode(s, "UTF-8")
        fun json(vararg pairs: Pair<String, Any?>): JSONObject {
            val o = JSONObject()
            for ((k, v) in pairs) o.put(k, v ?: JSONObject.NULL)
            return o
        }
    }
}

// JSON helpers: every field read with a default, because the dashboard
// moves and a missing key is a blank on screen, never a crash.
fun JSONObject.str(key: String, default: String = "") = optString(key, default) ?: default
fun JSONObject.int(key: String, default: Int = 0) = optInt(key, default)
fun JSONObject.bool(key: String, default: Boolean = false) = optBoolean(key, default)
fun JSONObject.obj(key: String): JSONObject = optJSONObject(key) ?: JSONObject()
fun JSONObject.arr(key: String): List<JSONObject> {
    val a = optJSONArray(key) ?: return emptyList()
    return (0 until a.length()).mapNotNull { a.optJSONObject(it) }
}
fun JSONObject.strs(key: String): List<String> {
    val a = optJSONArray(key) ?: return emptyList()
    return (0 until a.length()).map { a.optString(it) }
}
