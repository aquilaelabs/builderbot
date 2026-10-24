// Where the app keeps the dashboards it is paired with and the account's
// credential for each: an encrypted preferences file, keyed by the device's
// keystore, so a password never sits in plain text. Everything else the app
// remembers is ordinary preferences.
//
// More than one BuilderBot (R132): each pairing has a name, an address and
// an account, and one of them is current, which is the one the screens show
// and the phone is lent from. The watch and the live connection cover every
// pairing, each with its own memory of what it has already said, so a note
// from one is never mistaken for another's.
package dev.builderbot.app

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import org.json.JSONArray
import org.json.JSONObject

/** One dashboard the app is signed in to. `slot` is a small number of its
 *  own that keeps its notifications apart from another pairing's. */
data class Pairing(val id: String, val name: String, val server: String, val user: String,
                   val password: String, val slot: Int) {
    val label get() = name.ifBlank { server.removePrefix("https://").removePrefix("http://") }
}

class Store(context: Context) {
    private val secret: SharedPreferences = run {
        val key = MasterKey.Builder(context).setKeyScheme(MasterKey.KeyScheme.AES256_GCM).build()
        EncryptedSharedPreferences.create(
            context, "builderbot-secret", key,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM)
    }
    private val plain: SharedPreferences = context.getSharedPreferences("builderbot", Context.MODE_PRIVATE)

    init { migrate() }

    // The one pairing the app kept before R132 (server, user, password at
    // the top level) becomes the first of the list, named by its host.
    private fun migrate() {
        if (secret.contains("pairings")) return
        val server = secret.getString("server", "") ?: ""
        val user = secret.getString("user", "") ?: ""
        if (server.isBlank() || user.isBlank()) return
        val p = Pairing("p1", "", server, user, secret.getString("password", "") ?: "", 1)
        write(listOf(p))
        secret.edit().putString("current", p.id).remove("server").remove("user").remove("password").apply()
    }

    private fun write(ps: List<Pairing>) {
        val arr = JSONArray()
        for (p in ps) arr.put(JSONObject().put("id", p.id).put("name", p.name).put("server", p.server)
            .put("user", p.user).put("password", p.password).put("slot", p.slot))
        secret.edit().putString("pairings", arr.toString()).apply()
    }

    val pairings: List<Pairing>
        get() = try {
            val arr = JSONArray(secret.getString("pairings", "[]") ?: "[]")
            (0 until arr.length()).map { arr.getJSONObject(it) }.map {
                Pairing(it.optString("id"), it.optString("name"), it.optString("server"),
                        it.optString("user"), it.optString("password"), it.optInt("slot", 1))
            }.filter { it.id.isNotBlank() && it.server.isNotBlank() }
        } catch (e: Exception) { emptyList() }

    var current: String
        get() = secret.getString("current", "") ?: ""
        set(v) { secret.edit().putString("current", v).apply() }

    /** The pairing in front: the current one, or the first when the current
     *  was forgotten. */
    val pairing: Pairing? get() = pairings.let { ps -> ps.find { it.id == current } ?: ps.firstOrNull() }
    fun pairing(id: String): Pairing? = pairings.find { it.id == id }

    val server: String get() = pairing?.server ?: ""
    val user: String get() = pairing?.user ?: ""
    /** The current pairing's password, rewritten when the account changes it. */
    var password: String
        get() = pairing?.password ?: ""
        set(v) { val p = pairing ?: return; write(pairings.map { if (it.id == p.id) it.copy(password = v) else it }) }

    val signedIn get() = pairings.isNotEmpty()

    /** A new pairing, made current. The same address and account twice is
     *  the one pairing, renamed. */
    fun add(name: String, server: String, user: String, password: String): Pairing {
        val ps = pairings.toMutableList()
        val same = ps.indexOfFirst { it.server.trim() == server.trim() && it.user.trim() == user.trim() }
        val p = if (same >= 0) ps[same].copy(name = name.trim(), password = password).also { ps[same] = it }
                else Pairing("p" + System.currentTimeMillis().toString(36), name.trim(), server.trim(), user.trim(),
                             password, (ps.maxOfOrNull { it.slot } ?: 0) + 1).also { ps.add(it) }
        write(ps)
        current = p.id
        return p
    }

    /** A pairing forgotten, with its memory. The current moves to another,
     *  or to none. */
    fun forget(id: String) {
        val ps = pairings.filter { it.id != id }
        write(ps)
        memory(id).clear()
        if (current == id) current = ps.firstOrNull()?.id ?: ""
        if (ps.isEmpty()) secret.edit().clear().apply()
    }

    fun signOut() { pairing?.let { forget(it.id) } }

    fun api(): Api? = pairing?.let { api(it) }
    fun api(p: Pairing) = Api(p.server, p.user, p.password)

    // The watch: whether it runs, and how often it asks. Fifteen seconds is
    // the dashboard's own poll; a phone on battery may want a minute.
    var watch: Boolean
        get() = plain.getBoolean("watch", true)
        set(v) { plain.edit().putBoolean("watch", v).apply() }
    var pollSeconds: Int
        get() = plain.getInt("poll", 20)
        set(v) { plain.edit().putInt("poll", v.coerceIn(10, 300)).apply() }
    // Hear asks at once (R125): a foreground connection to the dashboard
    // instead of waiting on Android's alarm. Off until chosen.
    var live: Boolean
        get() = plain.getBoolean("live", false)
        set(v) { plain.edit().putBoolean("live", v).apply() }
    // The app asks for the phone's own lock (fingerprint, face, or its PIN)
    // every time it comes to the front (R133). Off until chosen.
    var lock: Boolean
        get() = plain.getBoolean("lock", false)
        set(v) { plain.edit().putBoolean("lock", v).apply() }

    // The color scheme, by the dashboard's name for it, on this device.
    var scheme: String
        get() = plain.getString("scheme", "Default") ?: "Default"
        set(v) { plain.edit().putString("scheme", v).apply() }
    // ...and which half of it: Dark, Light or System (R50 step 16). Dark for a
    // phone that never chose, which is what the app was before.
    var mode: String
        get() = plain.getString("mode", "Dark") ?: "Dark"
        set(v) { plain.edit().putString("mode", v).apply() }
    // Whether a session coming free is worth a notification.
    var turns: Boolean
        get() = plain.getBoolean("turns", true)
        set(v) { plain.edit().putBoolean("turns", v).apply() }

    /** What the watch has already told the person about, per pairing, so a
     *  notification is posted once per request and not on every poll, and
     *  one dashboard's news is never taken for another's. */
    inner class Memory(private val id: String) {
        private fun k(name: String) = "$id.$name"
        // The asks already notified, by id.
        var notifiedAsks: Set<String>
            get() = plain.getStringSet(k("asks"), emptySet()) ?: emptySet()
            set(v) { plain.edit().putStringSet(k("asks"), v).apply() }
        // The ongoing notes up now (a lent phone, a session allowed), by key,
        // so one that ended elsewhere leaves the shade.
        var ongoing: Set<String>
            get() = plain.getStringSet(k("ongoing"), emptySet()) ?: emptySet()
            set(v) { plain.edit().putStringSet(k("ongoing"), v).apply() }
        var lastAttention: String
            get() = plain.getString(k("attention"), "") ?: ""
            set(v) { plain.edit().putString(k("attention"), v).apply() }
        var lastPending: String
            get() = plain.getString(k("pending"), "") ?: ""
            set(v) { plain.edit().putString(k("pending"), v).apply() }
        var lastInvites: String
            get() = plain.getString(k("invites"), "") ?: ""
            set(v) { plain.edit().putString(k("invites"), v).apply() }
        // Which projects' sessions were busy (working, or testing under a
        // project that waits for its tests) at the last look, so a note is
        // posted when a session goes from busy to waiting on you and not on
        // every poll; lastTesting is which had a test run going, so the note
        // can say the tests finished.
        var lastWorking: Set<String>
            get() = plain.getStringSet(k("working"), emptySet()) ?: emptySet()
            set(v) { plain.edit().putStringSet(k("working"), v).apply() }
        var lastTesting: Set<String>
            get() = plain.getStringSet(k("testing"), emptySet()) ?: emptySet()
            set(v) { plain.edit().putStringSet(k("testing"), v).apply() }
        fun clear() {
            plain.edit().apply {
                for (n in listOf("asks", "ongoing", "attention", "pending", "invites", "working", "testing")) remove(k(n))
            }.apply()
        }
    }
    fun memory(id: String) = Memory(id)
}
