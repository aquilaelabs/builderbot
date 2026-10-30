// Versions in one place. AGP carries Kotlin itself since 9.0, so there is
// no kotlin.android plugin to pin; the Compose compiler is Kotlin's own
// plugin since 2.0, and its version is the Kotlin AGP bundles.
plugins {
    id("com.android.application") version "9.4.1" apply false
    id("org.jetbrains.kotlin.plugin.compose") version "2.4.20" apply false
}

// Where the build writes, on a node (B351). The tree there is on the
// projects share, and a directory emptied and removed in one build on NFS
// can fail to go: a file deleted while a process still holds it is renamed,
// not removed, and the directory around it is not empty. So a build on a
// node writes under the node's own disk: a job's cache folder when the
// agent hands one (BUILDERBOT_CACHE), else the session's own folder in the
// account's BuilderBot cache, which is on the node's disk and outlives the
// session. $HOME and not user.home: Java reads the latter from the account
// database, which on a node names the base home, and the base home's cache
// in a session's view is a tmpfs made for that session. Anywhere else (the
// workflow's hosted runner, a laptop) the build directory is Gradle's usual
// one, so app/build/outputs stays where those look for it; the bbApk task
// below puts the APK where it is asked either way.
val home: String? = System.getenv("HOME")
val scratch: String? = System.getenv("BUILDERBOT_CACHE")
    ?: if (System.getenv("BB_NODE") != null && home != null) {
        val account = System.getenv("BB_ACCOUNT_UID"); val project = System.getenv("BB_PROJECT")
        if (!account.isNullOrBlank() && !project.isNullOrBlank()) "$home/.cache/builderbot/u/$account/project/$project/gradle"
        else "$home/.cache/builderbot-gradle"
    } else null
if (scratch != null) {
    allprojects {
        layout.buildDirectory.set(File(scratch, "BuilderBot" + project.path.replace(':', '/')))
    }
}
