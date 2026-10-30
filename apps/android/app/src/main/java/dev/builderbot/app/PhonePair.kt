// Connecting this phone to a node from the phone itself (R114), in place of
// typing an address, a port and a code into the dashboard's Phone tab.
//
// Android shows the pairing code only in its own Wireless debugging screen,
// and no app can read it or turn debugging on: that is the person's step,
// and it stays theirs. What the app takes over is the rest:
//
// - the ports. adbd announces itself on the phone's own network with mDNS,
//   _adb-tls-pairing._tcp while the pairing dialog is open and
//   _adb-tls-connect._tcp while debugging is on, so NsdManager finds both
//   and nobody reads a number off the screen;
// - the code. Leaving the pairing dialog cancels it, which is why pairing
//   from the dashboard on this same phone never worked. A notification with
//   a reply box takes the six digits over the dialog without leaving it;
// - the rest is the controller's: /api/phone pair and connect, run on the
//   node, with this phone's address as the node reaches it (its VPN address
//   when a VPN is up, else its Wi-Fi one).
//
// Nothing here touches another app or reads the screen; it is network
// discovery on the phone's own network and calls to the person's own
// BuilderBot, so Play Protect has nothing new to look at.
package dev.builderbot.app

import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import androidx.core.app.NotificationCompat
import androidx.core.app.RemoteInput
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withTimeoutOrNull
import java.net.Inet4Address
import java.net.NetworkInterface
import kotlin.coroutines.resume

object PhonePair {
    const val ID_PAIR = 4100
    private const val KEY_CODE = "code"

    /** The addresses this phone has that a node could reach it on, the VPN's
     *  first: (address, what it is). A tunnel's interface names are tun, wg,
     *  tailscale, ppp or ipsec; Wi-Fi is wlan. */
    fun addresses(): List<Pair<String, String>> {
        val out = mutableListOf<Pair<String, String>>()
        try {
            for (ni in NetworkInterface.getNetworkInterfaces()) {
                if (!ni.isUp || ni.isLoopback) continue
                val name = ni.name.lowercase()
                val kind = when {
                    listOf("tun", "wg", "tailscale", "ppp", "ipsec").any { name.startsWith(it) } -> "VPN"
                    name.startsWith("wlan") -> "Wi-Fi"
                    else -> continue
                }
                for (a in ni.inetAddresses) if (a is Inet4Address) out += a.hostAddress!! to kind
            }
        } catch (_: Exception) {}
        return out.sortedBy { if (it.second == "VPN") 0 else 1 }
    }

    /** The port of the first service of `type` this phone announces, found
     *  within `ms`, or null. Resolved for its port alone: the address the
     *  node uses is picked from addresses(), since mDNS answers with the
     *  Wi-Fi one and a node across a VPN does not reach that. */
    suspend fun port(context: Context, type: String, ms: Long = 8000): Int? {
        val nsd = context.getSystemService(NsdManager::class.java) ?: return null
        val held = arrayOfNulls<NsdManager.DiscoveryListener>(1)
        val stop = { held[0]?.let { l -> try { nsd.stopServiceDiscovery(l) } catch (_: Exception) {} }; held[0] = null }
        return try {
            withTimeoutOrNull(ms) {
                suspendCancellableCoroutine { cont ->
                    var done = false
                    held[0] = object : NsdManager.DiscoveryListener {
                        override fun onDiscoveryStarted(t: String) {}
                        override fun onDiscoveryStopped(t: String) {}
                        override fun onStartDiscoveryFailed(t: String, e: Int) {
                            if (!done) { done = true; cont.resume(null) }
                        }
                        override fun onStopDiscoveryFailed(t: String, e: Int) {}
                        override fun onServiceLost(s: NsdServiceInfo) {}
                        override fun onServiceFound(s: NsdServiceInfo) {
                            @Suppress("DEPRECATION")
                            nsd.resolveService(s, object : NsdManager.ResolveListener {
                                override fun onResolveFailed(s: NsdServiceInfo, e: Int) {}
                                override fun onServiceResolved(s: NsdServiceInfo) {
                                    if (!done && s.port > 0) { done = true; cont.resume(s.port) }
                                }
                            })
                        }
                    }
                    nsd.discoverServices(type, NsdManager.PROTOCOL_DNS_SD, held[0])
                }
            }
        } finally { stop() }
    }

    /** The notification the six digits are typed into, over Android's pairing
     *  dialog, carrying where to pair: the node, this phone's address and the
     *  pairing port found. */
    fun ask(context: Context, node: String, ip: String, port: Int) {
        val reply = RemoteInput.Builder(KEY_CODE).setLabel("Pairing code").build()
        val i = Intent(context, PairReceiver::class.java).apply {
            putExtra("node", node); putExtra("ip", ip); putExtra("port", port)
        }
        // Mutable: a reply box writes its text into the intent.
        val pi = PendingIntent.getBroadcast(context, ID_PAIR, i,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_MUTABLE)
        val nm = context.getSystemService(NotificationManager::class.java)
        nm.notify(ID_PAIR, NotificationCompat.Builder(context, App.CH_ASK)
            .setSmallIcon(R.drawable.ic_stat_bb)
            .setContentTitle("Pair with BuilderBot")
            .setContentText("Type the six digits Android shows, here, without leaving that screen")
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setOnlyAlertOnce(true)
            .addAction(NotificationCompat.Action.Builder(0, "Pairing code", pi)
                .addRemoteInput(reply).build())
            .setTimeoutAfter(5 * 60_000)
            .build())
    }

    fun said(context: Context, text: String) {
        context.getSystemService(NotificationManager::class.java).notify(ID_PAIR,
            NotificationCompat.Builder(context, App.CH_NOTE)
                .setSmallIcon(R.drawable.ic_stat_bb)
                .setContentTitle(text)
                .setContentIntent(Watch.openApp(context, "phone"))
                .setAutoCancel(true)
                .setTimeoutAfter(60_000)
                .build())
    }

    /** Pair on the node, then connect it: the connect port is the one
     *  _adb-tls-connect announces, found here, or the node's own scan. */
    suspend fun pairAndConnect(context: Context, api: Api, node: String, ip: String, port: Int, code: String): String {
        api.phonePair(node, ip, port, code)
        val cport = port(context, "_adb-tls-connect._tcp", 6000)
        api.phoneConnect(node, ip, cport)
        return "Paired and connected"
    }
}

class PairReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val code = RemoteInput.getResultsFromIntent(intent)?.getCharSequence("code")?.toString()
            ?.filter { it.isDigit() } ?: ""
        val node = intent.getStringExtra("node") ?: return
        val ip = intent.getStringExtra("ip") ?: return
        val port = intent.getIntExtra("port", 0)
        val api = Store(context).api() ?: return
        if (code.length != 6) { PhonePair.said(context, "The pairing code is six digits"); return }
        PhonePair.said(context, "Pairing with BuilderBot…")
        val pending = goAsync()
        Thread {
            val said = try {
                runBlocking { PhonePair.pairAndConnect(context, api, node, ip, port, code) }
            } catch (e: Exception) {
                "Could not pair: ${e.message}"
            }
            PhonePair.said(context, said)
            pending.finish()
        }.start()
    }
}
