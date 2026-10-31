// This phone (R114): connecting it to a node and lending it to a project,
// from the phone, in place of typing its address, port and code into the
// dashboard's Phone tab. PhonePair.kt does the finding and the pairing; this
// is the screen that walks a person through it and shows where it stands.
package dev.builderbot.app.ui

import android.content.Intent
import android.provider.Settings
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import dev.builderbot.app.PhonePair
import dev.builderbot.app.Store
import dev.builderbot.app.arr
import dev.builderbot.app.bool
import dev.builderbot.app.int
import dev.builderbot.app.obj
import dev.builderbot.app.str
import dev.builderbot.app.strs
import kotlinx.coroutines.launch

@Composable
fun PhoneScreen(store: Store) {
    val api = store.api() ?: return
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var said by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf("") }
    val (got, reload) = load("phone") { api.phone() }
    val nodes = got.value?.arr("nodes")?.filter { it.bool("live") } ?: emptyList()
    var nodeId by remember { mutableStateOf("") }
    val node = nodes.find { it.str("id") == nodeId } ?: nodes.firstOrNull()
    val addrs = remember { PhonePair.addresses() }
    var ip by remember { mutableStateOf(addrs.firstOrNull()?.first ?: "") }
    var lendTo by remember { mutableStateOf("") }
    var hours by remember { mutableStateOf(1) }

    fun act(word: String, block: suspend () -> String) {
        busy = word; said = ""
        scope.launch {
            said = try { block() } catch (e: Exception) { e.message ?: "it did not work" }
            busy = ""
            reload()
        }
    }

    Pull(got.value == null && got.error == null, reload) {
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp)) {
            Text("This phone", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold, color = Ink)
            Dim("Connect it to a node over Android's Wireless debugging, then lend it to a project: that project's sessions install, run, see and touch its own app here, and anything else still asks you.")
            got.error?.let { Problem(it) }
            if (got.value != null && nodes.isEmpty()) Problem("No node with adb is dialing in: install android-tools on one from the Library.")
            if (node != null) {
                SectionHead("Node", inset = false)
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    for (n in nodes) FilterChip(selected = n.str("id") == node.str("id"),
                        onClick = { nodeId = n.str("id") }, label = { Text(n.str("name")) })
                }
                val dev = node.obj("phone")
                val connected = dev.length() > 0
                Panel(Modifier.fillMaxWidth().padding(top = 8.dp)) {
                    Column(Modifier.padding(12.dp)) {
                        Text(if (connected) "${dev.str("model").ifBlank { "A phone" }} is connected on ${node.str("name")}"
                             else "No phone connected on ${node.str("name")}", color = if (connected) Ink else Dim)
                        if (connected && node.obj("owner").length() > 0)
                            Dim("connected by ${node.obj("owner").str("name")}" + if (node.bool("mine")) " (you)" else "")
                    }
                }

                SectionHead("Connect", inset = false)
                Dim("The address the node reaches this phone on" + if (addrs.any { it.second == "VPN" }) ", your VPN's first:" else ":")
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    for ((a, kind) in addrs) FilterChip(selected = ip == a, onClick = { ip = a }, label = { Text("$kind $a") })
                }
                if (addrs.isEmpty()) Problem("This phone has no Wi-Fi or VPN address: Wireless debugging needs Wi-Fi.")
                Spacer(Modifier.height(6.dp))
                Text("1. Turn on Wireless debugging", color = Ink)
                Button(onClick = {
                    context.startActivity(Intent(Settings.ACTION_APPLICATION_DEVELOPMENT_SETTINGS)
                        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
                }) { Text("Open Developer options") }
                Dim("Paired with this node before? Press Connect, and that is all.")
                Button(enabled = ip.isNotBlank() && busy.isEmpty(), onClick = {
                    act("connecting") {
                        val p = PhonePair.port(context, "_adb-tls-connect._tcp", 6000)
                        api.phoneConnect(node.str("id"), ip, p)
                        "Connected"
                    }
                }) { Text("Connect") }
                Spacer(Modifier.height(6.dp))
                Text("2. Or pair it the first time", color = Ink)
                Dim("In Wireless debugging, tap Pair device with pairing code and keep that screen open. Press Pair here first: a notification arrives, and the six digits go into it, typed over Android's screen.")
                Button(enabled = ip.isNotBlank() && busy.isEmpty(), onClick = {
                    act("looking for the pairing screen") {
                        val p = PhonePair.port(context, "_adb-tls-pairing._tcp", 60_000)
                            ?: return@act "Did not find the pairing screen within a minute: open Pair device with pairing code, then press Pair again"
                        PhonePair.ask(context, node.str("id"), ip, p)
                        "Now type the six digits into the BuilderBot notification"
                    }
                }) { Text("Pair") }

                val lease = node.obj("lease")
                if (connected && node.bool("mine")) {
                    SectionHead("Lend to a project", inset = false)
                    if (lease.length() > 0) {
                        val left = if (lease.isNull("left")) "until taken back" else "${lease.int("left") / 60} min left"
                        Panel(Modifier.fillMaxWidth()) {
                            Column(Modifier.padding(12.dp)) {
                                Text("Lent to ${lease.str("project")}, $left", color = Ink)
                                Dim(if (lease.strs("pkgs").isEmpty()) "its sessions may install one of its builds; then that app, and nothing else"
                                    else "its sessions drive ${lease.strs("pkgs").joinToString(", ")}, and nothing else, without asking")
                            }
                        }
                        Button(enabled = busy.isEmpty(), onClick = {
                            act("taking it back") { api.phoneTakeBack(node.str("id")); "Taken back" }
                        }) { Text("Take back") }
                    } else {
                        val ps = node.strs("lendable")
                        if (ps.isEmpty()) Problem("No project of yours runs on ${node.str("name")}, so there is none to lend it to.")
                        else {
                            if (lendTo !in ps) lendTo = ps.first()
                            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                                for (p in ps) FilterChip(selected = lendTo == p, onClick = { lendTo = p }, label = { Text(p) })
                            }
                            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                                for ((h, label) in listOf(1 to "1 hour", 4 to "4 hours", 0 to "until taken back"))
                                    FilterChip(selected = hours == h, onClick = { hours = h }, label = { Text(label) })
                            }
                            Button(enabled = busy.isEmpty(), onClick = {
                                act("lending") { api.phoneLend(node.str("id"), lendTo, hours); "Lent to $lendTo" }
                            }) { Text("Lend") }
                        }
                    }
                }
            }
            if (busy.isNotEmpty()) Row(verticalAlignment = Alignment.CenterVertically) { Dim("$busy…") }
            if (said.isNotEmpty()) Text(said, color = Note, modifier = Modifier.padding(top = 8.dp))
        }
    }
}
