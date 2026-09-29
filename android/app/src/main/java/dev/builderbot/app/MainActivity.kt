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
import androidx.activity.ComponentActivity
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
import dev.builderbot.app.ui.ProfileScreen
import dev.builderbot.app.ui.ProjectScreen
import dev.builderbot.app.ui.ToolsScreen
import dev.builderbot.app.ui.UsersScreen

class MainActivity : ComponentActivity() {
    private val askNotifications = registerForActivityResult(ActivityResultContracts.RequestPermission()) {}

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (Build.VERSION.SDK_INT >= 33 &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED)
            askNotifications.launch(Manifest.permission.POST_NOTIFICATIONS)
        setContent { BuilderBotApp(intent.getStringExtra("screen") ?: "") }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        setContent { BuilderBotApp(intent.getStringExtra("screen") ?: "") }
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
fun BuilderBotApp(openOn: String) {
    val context = androidx.compose.ui.platform.LocalContext.current
    val store = remember { Store(context).also { dev.builderbot.app.ui.Schemes.pick(it.scheme) } }
    var signedIn by remember { mutableStateOf(store.signedIn) }
    // Nobody is an administrator until the dashboard says so, and the
    // answer survives a rotation (B275): a user saw the Nodes tab until
    // Home reloaded.
    var isAdmin by rememberSaveable { mutableStateOf(false) }
    var waiting by rememberSaveable { mutableStateOf(0) }
    BuilderBotTheme {
        if (!signedIn) {
            LoginScreen(store) { admin -> isAdmin = admin; signedIn = true; Watch.startIfWanted(context) }
            return@BuilderBotTheme
        }
        // The watch while the app is open: its own clock, on the interval
        // set under More, and nothing in the shade for it. The alarm takes
        // over when the app is not on screen (Watch.startIfWanted).
        val lifecycle = androidx.lifecycle.compose.LocalLifecycleOwner.current
        LaunchedEffect(signedIn) {
            lifecycle.repeatOnLifecycle(androidx.lifecycle.Lifecycle.State.STARTED) {
                while (true) {
                    val api = store.api()
                    if (api != null && store.watch) {
                        try { Watch.tick(context, api, store) }
                        catch (e: ApiError) { if (e.status == 401 || e.status == 403) { Watch.signedOut(context); store.signOut(); signedIn = false; return@repeatOnLifecycle } }
                        catch (e: Exception) { /* a missed round; the next one asks again */ }
                    }
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
            NavHost(nav, startDestination = if (openOn in setOf("approvals", "nodes")) openOn else "home",
                    modifier = Modifier.padding(pad)) {
                composable("home") { HomeScreen(store, onAdmin = { isAdmin = it }, onWaiting = { waiting = it }, openProject = { nav.navigate("project/$it") }) }
                composable("project/{name}") { e -> ProjectScreen(store, e.arguments?.getString("name") ?: "") }
                composable("approvals") { ApprovalsScreen(store) }
                composable("nodes") { NodesScreen(store) }
                composable("more") { MoreScreen(store, isAdmin, nav, onSignOut = { Watch.stop(context); store.signOut(); signedIn = false }) }
                composable("users") { UsersScreen(store) }
                composable("tools") { ToolsScreen(store, isAdmin) }
                composable("profile") { ProfileScreen(store) }
                composable("jobs") { JobsScreen(store) }
                composable("whatsnew") { WhatsNewScreen(store) }
            }
        }
    }
}
