// The dashboard's API, as the app speaks it: Basic auth on every request
// (the same credential the browser sends), JSON in and out, one place that
// knows the server's address. Kept to the platform's own HTTP client and
// org.json so the app carries no networking stack of its own — the surface
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
    suspend fun todo(project: String) = get("/api/todo?project=${enc(project)}")
    suspend fun todoAdd(project: String, text: String) =
        post("/api/todo", json("project" to project, "action" to "add", "text" to text))
    suspend fun todoShelve(project: String, id: Any) =
        post("/api/todo", json("project" to project, "action" to "shelve", "id" to id))
    suspend fun todoRemove(project: String, id: Any, why: String) =
        post("/api/todo", json("project" to project, "action" to "remove", "id" to id, "why" to why))
    suspend fun bugs(project: String) = get("/api/bugs?project=${enc(project)}")
    suspend fun bugAdd(project: String, title: String, severity: String, area: String, repro: String) =
        post("/api/bugs", json("project" to project, "action" to "add", "title" to title,
                               "severity" to severity, "area" to area, "repro" to repro))
    suspend fun bugStatus(project: String, id: Any, status: String, note: String) =
        post("/api/bugs", json("project" to project, "action" to "status", "id" to id,
                               "status" to status, "note" to note))
    suspend fun rules(project: String) = get("/api/rules?project=${enc(project)}")
    suspend fun artifacts(project: String) = get("/api/artifacts?project=${enc(project)}")
    suspend fun git(project: String) = get("/api/git?project=${enc(project)}&what=status")
    suspend fun nodes() = get("/api/v1/nodes")
    suspend fun nodeAct(id: String, action: String) =
        post("/api/v1/nodes", json("action" to action, "id" to id))
    suspend fun users() = get("/api/users")
    suspend fun profile() = get("/api/profile")
    suspend fun profileSave(fields: Map<String, String>) =
        post("/api/profile", json("action" to "save", "profile" to JSONObject(fields)))
    suspend fun password(current: String, next: String) =
        post("/api/profile", json("action" to "password", "current" to current, "password" to next))
    suspend fun prefs(project: String, patch: Map<String, Any>) =
        post("/api/prefs", JSONObject(patch).put("project", project))

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
