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
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
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

// The dashboard's own palette, so the app reads as the same thing: the dark
// ground, the accent blue, amber for a question, red for stopped work.
val Accent = Color(0xFF58A6FF)
val Warn = Color(0xFFD29922)
val Bad = Color(0xFFE5534B)
val Ok = Color(0xFF3FB950)

@Composable
fun BuilderBotTheme(content: @Composable () -> Unit) {
    val dark = isSystemInDarkTheme()
    val scheme = if (dark) darkColorScheme(
        primary = Accent, background = Color(0xFF0F141A), surface = Color(0xFF161B22),
        surfaceVariant = Color(0xFF1A1F26), onBackground = Color(0xFFE6EDF3), onSurface = Color(0xFFE6EDF3),
        error = Bad)
    else lightColorScheme(primary = Color(0xFF0969DA), error = Bad)
    MaterialTheme(colorScheme = scheme, content = content)
}

data class Tab(val route: String, val label: String, val icon: ImageVector)

@Composable
fun BuilderBotApp(openOn: String) {
    val context = androidx.compose.ui.platform.LocalContext.current
    val store = remember { Store(context) }
    var signedIn by remember { mutableStateOf(store.signedIn) }
    var isAdmin by remember { mutableStateOf(true) }
    BuilderBotTheme {
        if (!signedIn) {
            LoginScreen(store) { admin -> isAdmin = admin; signedIn = true; WatchService.startIfWanted(context) }
            return@BuilderBotTheme
        }
        val nav = rememberNavController()
        val tabs = listOf(
            Tab("home", "Projects", Icons.Filled.Home),
            Tab("approvals", "Approvals", Icons.Filled.Notifications),
            Tab("nodes", "Nodes", Icons.Filled.Build),
            Tab("more", "More", Icons.Filled.Menu),
        ).filter { it.route != "nodes" || isAdmin }
        val entry by nav.currentBackStackEntryAsState()
        val here = entry?.destination?.route ?: "home"
        Scaffold(bottomBar = {
            NavigationBar {
                for (t in tabs) NavigationBarItem(
                    selected = here.startsWith(t.route),
                    onClick = { nav.navigate(t.route) { launchSingleTop = true; popUpTo("home") } },
                    icon = { Icon(t.icon, contentDescription = t.label) },
                    label = { Text(t.label) })
            }
        }) { pad ->
            NavHost(nav, startDestination = if (openOn in setOf("approvals", "nodes")) openOn else "home",
                    modifier = Modifier.padding(pad)) {
                composable("home") { HomeScreen(store, onAdmin = { isAdmin = it }, openProject = { nav.navigate("project/$it") }) }
                composable("project/{name}") { e -> ProjectScreen(store, e.arguments?.getString("name") ?: "") }
                composable("approvals") { ApprovalsScreen(store) }
                composable("nodes") { NodesScreen(store) }
                composable("more") { MoreScreen(store, isAdmin, nav, onSignOut = { WatchService.stop(context); store.signOut(); signedIn = false }) }
                composable("users") { UsersScreen(store) }
                composable("tools") { ToolsScreen(store, isAdmin) }
                composable("profile") { ProfileScreen(store) }
            }
        }
    }
}
