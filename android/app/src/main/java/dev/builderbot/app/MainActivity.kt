// The app: one activity, a bottom bar, and screens for what the dashboard's
// sidebar and notebook do, minus the terminals. A session's Claude and its
// shell are the browser's; everything else (projects, the notebook, the
// approvals, the nodes, the accounts, your profile) is here, in the shape
// an Android app takes rather than the tabs a browser page needs.
package dev.builderbot.app

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.fragment.app.FragmentActivity
import androidx.biometric.BiometricManager
import androidx.biometric.BiometricPrompt
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.material3.Button
import androidx.compose.runtime.key
import androidx.compose.ui.Alignment
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Build
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.List
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material.icons.filled.Notifications
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Shapes
import androidx.compose.material3.Badge
import androidx.compose.material3.BadgedBox
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.ui.unit.dp
import dev.builderbot.app.ui.AccentDeep
import dev.builderbot.app.ui.Bg
import dev.builderbot.app.ui.Bad
import dev.builderbot.app.ui.Dim
import dev.builderbot.app.ui.Ink
import dev.builderbot.app.ui.Line
import dev.builderbot.app.ui.Note
import dev.builderbot.app.ui.Panel
import dev.builderbot.app.ui.Sunk
import androidx.compose.material3.Text
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.LaunchedEffect
import androidx.lifecycle.repeatOnLifecycle
import dev.builderbot.app.ui.Warn
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.core.content.ContextCompat
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import dev.builderbot.app.ui.ApprovalsScreen
import dev.builderbot.app.ui.HomeScreen
import dev.builderbot.app.ui.JobsScreen
import dev.builderbot.app.ui.WhatsNewScreen
import dev.builderbot.app.ui.LoginScreen
import dev.builderbot.app.ui.MoreScreen
import dev.builderbot.app.ui.NodesScreen
import dev.builderbot.app.ui.PhoneScreen
import dev.builderbot.app.ui.ProfileScreen
import dev.builderbot.app.ui.ProjectScreen
import dev.builderbot.app.ui.ToolsScreen
import dev.builderbot.app.ui.UsersScreen

// A FragmentActivity rather than a ComponentActivity: BiometricPrompt (the
// app's lock, R133) is a fragment of the activity it is shown over.
class MainActivity : FragmentActivity() {
    private val askNotifications = registerForActivityResult(ActivityResultContracts.RequestPermission()) {}
    // The lock (R133): locked every time the app leaves the screen, and the
    // phone's own lock asked for when it comes back, while the setting is
    // on. `prompting` keeps the credential screen (its own activity on
    // older Android) from reading as the app leaving.
    val locked = mutableStateOf(true)
    private var prompting = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (Build.VERSION.SDK_INT >= 33 &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED)
            askNotifications.launch(Manifest.permission.POST_NOTIFICATIONS)
        setContent { BuilderBotApp(intent.getStringExtra("screen") ?: "", this) }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        setContent { BuilderBotApp(intent.getStringExtra("screen") ?: "", this) }
    }

    override fun onStart() {
        super.onStart()
        if (Store(this).lock && locked.value) unlock() else locked.value = false
    }

    override fun onStop() {
        super.onStop()
        if (!prompting) locked.value = true
    }

    /** Ask for the phone's lock. Canceled or failed, the app stays veiled
     *  with an Unlock button, and nothing of it is shown. */
    fun unlock() {
        if (prompting) return
        prompting = true
        val prompt = BiometricPrompt(this, ContextCompat.getMainExecutor(this),
            object : BiometricPrompt.AuthenticationCallback() {
                override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) {
                    prompting = false; locked.value = false
                }
                override fun onAuthenticationError(code: Int, msg: CharSequence) { prompting = false }
            })
        prompt.authenticate(BiometricPrompt.PromptInfo.Builder()
            .setTitle("Unlock BuilderBot")
            .setSubtitle("Your fingerprint, face or phone PIN")
            .setAllowedAuthenticators(allowed())
            .build())
    }

    companion object {
        /** The lock kinds the phone may answer with: a strong biometric or
         *  the device credential, which Android pairs only from 11 on; a
         *  weaker biometric with the credential before that. */
        fun allowed(): Int =
            if (Build.VERSION.SDK_INT >= 30) BiometricManager.Authenticators.BIOMETRIC_STRONG or BiometricManager.Authenticators.DEVICE_CREDENTIAL
            else BiometricManager.Authenticators.BIOMETRIC_WEAK or BiometricManager.Authenticators.DEVICE_CREDENTIAL
        /** Whether this phone has a lock to ask for. */
        fun canLock(context: android.content.Context): Boolean =
            BiometricManager.from(context).canAuthenticate(allowed()) == BiometricManager.BIOMETRIC_SUCCESS
    }
}

// The dashboard's own schemes (ui/Theme.kt holds them and the tokens; the
// one in front is chosen under More), so the app reads as the same thing: a filled accent surface is the deep green with
// ink on it, the surface is the panel color, the edge is the line token,
// and the corners are the site's two radii. The site is dark by design and
// so is this; a light system setting still gets a readable page rather than
// a second design.
@Composable
fun BuilderBotTheme(content: @Composable () -> Unit) {
    // One palette, the dashboard's, whatever the system theme: the screens
    // paint their panels and text from Parts.kt's tokens directly, so a
    // light Material scheme underneath them put black headings on the dark
    // background (seen on an emulator whose system theme was light).
    val scheme = darkColorScheme(
        primary = AccentDeep, onPrimary = Ink, primaryContainer = AccentDeep, onPrimaryContainer = Ink,
        secondary = Note, secondaryContainer = AccentDeep, onSecondaryContainer = Ink,
        tertiary = Note, background = Bg, onBackground = Ink, surface = Panel, onSurface = Ink,
        surfaceVariant = Sunk, onSurfaceVariant = Dim, surfaceContainer = Panel,
        surfaceContainerHigh = Panel, surfaceContainerHighest = Panel, surfaceContainerLow = Bg, outline = Line, outlineVariant = Line,
        error = Bad, onError = Ink)
    MaterialTheme(colorScheme = scheme,
        shapes = Shapes(extraSmall = RoundedCornerShape(4.dp), small = RoundedCornerShape(6.dp),
                        medium = RoundedCornerShape(8.dp), large = RoundedCornerShape(8.dp)),
        content = content)
}

data class Tab(val route: String, val label: String, val icon: ImageVector)

@Composable
fun BuilderBotApp(openOn: String, activity: MainActivity) {
    val context = androidx.compose.ui.platform.LocalContext.current
    val store = remember { Store(context).also { dev.builderbot.app.ui.Schemes.pick(it.scheme) } }
    var signedIn by remember { mutableStateOf(store.signedIn) }
    // Which pairing is in front (R132): the screens are keyed by it, so a
    // switch redraws every one of them from the other dashboard.
    var current by remember { mutableStateOf(store.pairing?.id ?: "") }
    val locked by activity.locked
    if (locked && store.lock) {
        BuilderBotTheme {
            Column(Modifier.fillMaxSize().padding(24.dp), verticalArrangement = Arrangement.Center,
                   horizontalAlignment = Alignment.CenterHorizontally) {
                Text("BuilderBot", style = MaterialTheme.typography.headlineMedium, color = Ink)
                Spacer(Modifier.height(16.dp))
                Button(onClick = { activity.unlock() }) { Text("Unlock") }
            }
        }
        return
    }
    // Nobody is an administrator until the dashboard says so, and the
    // answer survives a rotation (B275): a user saw the Nodes tab until
    // Home reloaded.
    var isAdmin by rememberSaveable { mutableStateOf(false) }
    // What the account may install (R137): toolchains-write, from the same
    // can the page reads; an administrator until Home has said.
    var mayTools by rememberSaveable { mutableStateOf(false) }
    var waiting by rememberSaveable { mutableStateOf(0) }
    BuilderBotTheme {
        if (!signedIn) {
            LoginScreen(store) { admin -> isAdmin = admin; mayTools = admin; signedIn = true; current = store.pairing?.id ?: ""
                                 Watch.startIfWanted(context); Live.startIfWanted(context) }
            return@BuilderBotTheme
        }
        key(current) {
        // The watch while the app is open: its own clock, on the interval
        // set under More, and nothing in the shade for it. The alarm takes
        // over when the app is not on screen (Watch.startIfWanted).
        val lifecycle = androidx.lifecycle.compose.LocalLifecycleOwner.current
        LaunchedEffect(signedIn) {
            lifecycle.repeatOnLifecycle(androidx.lifecycle.Lifecycle.State.STARTED) {
                // On screen is when Android lets the live connection start
                // (R125): it was stopped, or its start was refused, behind.
                Live.startIfWanted(context)
                while (true) {
                    // Every pairing (R132): one whose sign-in is refused is
                    // forgotten by tickAll, and the rest go on.
                    if (store.watch) Watch.tickAll(context, store)
                    if (!store.signedIn) { signedIn = false; return@repeatOnLifecycle }
                    if (store.pairing?.id != current) current = store.pairing?.id ?: ""
                    kotlinx.coroutines.delay(store.pollSeconds * 1000L)
                }
            }
        }
        val nav = rememberNavController()
        val tabs = listOf(
            Tab("home", "Projects", Icons.Filled.Home),
            Tab("approvals", "Approvals", Icons.Filled.Notifications),
            Tab("nodes", "Nodes", Icons.Filled.Build),
            Tab("more", "More", Icons.Filled.Menu),
        ).filter { it.route != "nodes" || isAdmin }
        // A note about one project opens on that project, over Home, so
        // Back goes to the list.
        LaunchedEffect(openOn) { if (openOn.startsWith("project/")) nav.navigate(openOn) { launchSingleTop = true } }
        val entry by nav.currentBackStackEntryAsState()
        val here = entry?.destination?.route ?: "home"
        Scaffold(containerColor = Bg, bottomBar = {
            NavigationBar(containerColor = Panel) {
                for (t in tabs) NavigationBarItem(
                    selected = here.startsWith(t.route),
                    onClick = { nav.navigate(t.route) { launchSingleTop = true; popUpTo("home") } },
                    icon = {
                        // The count of what waits on the person, on the tab
                        // it lives under: the bell's dot, in the shape a phone
                        // has for it.
                        if (t.route == "approvals" && waiting > 0)
                            BadgedBox(badge = { Badge(containerColor = Warn, contentColor = Bg) { Text("$waiting") } }) {
                                Icon(t.icon, contentDescription = t.label) }
                        else Icon(t.icon, contentDescription = t.label)
                    },
                    label = { Text(t.label) },
                    colors = NavigationBarItemDefaults.colors(
                        selectedIconColor = Ink, selectedTextColor = Ink, indicatorColor = AccentDeep,
                        unselectedIconColor = Dim, unselectedTextColor = Dim))
            }
        }) { pad ->
            NavHost(nav, startDestination = if (openOn in setOf("approvals", "nodes", "phone")) openOn else "home",
                    modifier = Modifier.padding(pad)) {
                composable("home") { HomeScreen(store, onAdmin = { isAdmin = it }, onWaiting = { waiting = it }, openProject = { nav.navigate("project/$it") },
                                                 onSwitch = { store.current = it; current = it }, onTools = { mayTools = it }) }
                composable("project/{name}") { e -> ProjectScreen(store, e.arguments?.getString("name") ?: "") }
                composable("approvals") { ApprovalsScreen(store) }
                composable("nodes") { NodesScreen(store) }
                composable("more") { MoreScreen(store, isAdmin, nav,
                    onSignOut = { store.signOut(); if (!store.signedIn) { Watch.stop(context); Live.stop(context); signedIn = false }
                                  else { current = store.pairing?.id ?: ""; Live.startIfWanted(context) } },
                    onSwitch = { store.current = it; current = it }) }
                composable("add") { LoginScreen(store, adding = true) { _ -> current = store.pairing?.id ?: ""
                                                                         Live.startIfWanted(context); nav.popBackStack() } }
                composable("users") { UsersScreen(store) }
                composable("tools") { ToolsScreen(store, mayTools) }
                composable("profile") { ProfileScreen(store) }
                composable("jobs") { JobsScreen(store) }
                composable("whatsnew") { WhatsNewScreen(store) }
                composable("phone") { PhoneScreen(store) }
            }
        }
        }   // key(current)
    }
}
