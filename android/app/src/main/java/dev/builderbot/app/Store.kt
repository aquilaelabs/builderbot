// Where the app keeps the dashboard's address and the account's credential:
// an encrypted preferences file, keyed by the device's keystore, so the
// password never sits in plain text. Everything else the app remembers is
// ordinary preferences.
package dev.builderbot.app

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

class Store(context: Context) {
    private val secret: SharedPreferences = run {
        val key = MasterKey.Builder(context).setKeyScheme(MasterKey.KeyScheme.AES256_GCM).build()
        EncryptedSharedPreferences.create(
            context, "builderbot-secret", key,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM)
    }
    private val plain: SharedPreferences = context.getSharedPreferences("builderbot", Context.MODE_PRIVATE)

    var server: String
        get() = secret.getString("server", "") ?: ""
        set(v) { secret.edit().putString("server", v.trim()).apply() }
    var user: String
        get() = secret.getString("user", "") ?: ""
        set(v) { secret.edit().putString("user", v.trim()).apply() }
    var password: String
        get() = secret.getString("password", "") ?: ""
        set(v) { secret.edit().putString("password", v).apply() }

    val signedIn get() = server.isNotBlank() && user.isNotBlank()

    fun signOut() { secret.edit().clear().apply() }

    // The watch: whether it runs, and how often it asks. Fifteen seconds is
    // the dashboard's own poll; a phone on battery may want a minute.
    var watch: Boolean
        get() = plain.getBoolean("watch", true)
        set(v) { plain.edit().putBoolean("watch", v).apply() }
    var pollSeconds: Int
        get() = plain.getInt("poll", 20)
        set(v) { plain.edit().putInt("poll", v.coerceIn(10, 300)).apply() }

    // What the watch has already told the person about, so a notification
    // is posted once per request and not on every poll.
    var notifiedAsks: Set<String>
        get() = plain.getStringSet("asks", emptySet()) ?: emptySet()
        set(v) { plain.edit().putStringSet("asks", v).apply() }
    // The ongoing notes up now (a lent phone, a session allowed), by id, so
    // one that ended elsewhere leaves the shade.
    var ongoing: Set<String>
        get() = plain.getStringSet("ongoing", emptySet()) ?: emptySet()
        set(v) { plain.edit().putStringSet("ongoing", v).apply() }
    var lastAttention: String
        get() = plain.getString("attention", "") ?: ""
        set(v) { plain.edit().putString("attention", v).apply() }
    var lastPending: String
        get() = plain.getString("pending", "") ?: ""
        set(v) { plain.edit().putString("pending", v).apply() }
    var lastInvites: String
        get() = plain.getString("invites", "") ?: ""
        set(v) { plain.edit().putString("invites", v).apply() }

    // The color scheme, by the dashboard's name for it, on this device.
    var scheme: String
        get() = plain.getString("scheme", "Default") ?: "Default"
        set(v) { plain.edit().putString("scheme", v).apply() }
    // Whether a session coming free is worth a notification, and which
    // projects' sessions were busy (working, or testing under a project
    // that waits for its tests) at the last look, so one is posted when a
    // session goes from busy to waiting on you and not on every poll.
    // lastTesting is which had a test run going, so the note can say the
    // tests finished.
    var turns: Boolean
        get() = plain.getBoolean("turns", true)
        set(v) { plain.edit().putBoolean("turns", v).apply() }
    var lastWorking: Set<String>
        get() = plain.getStringSet("working", emptySet()) ?: emptySet()
        set(v) { plain.edit().putStringSet("working", v).apply() }
    var lastTesting: Set<String>
        get() = plain.getStringSet("testing", emptySet()) ?: emptySet()
        set(v) { plain.edit().putStringSet("testing", v).apply() }

    fun api(): Api? = if (signedIn) Api(server, user, password) else null
}
