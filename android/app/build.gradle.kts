// The companion app.
//
// Its VERSION is BuilderBot's, not a number of its own: the app ships from
// this repository, talks to this dashboard, and the APK the workflow names
// already carries `bb version --file`. A hand-kept versionName drifted from
// that immediately (it still said 0.1.0 on the day the project reached
// 0.5.0), so the build takes both from `bb version` when it is told them
// (-PbbVersion, -PbbCode, which the workflow passes) and falls back to
// reading them itself. A checkout with no bb and no git still builds; it
// just says so in the name.
//
// TARGET_API is the number of the dashboard's API surface
// this build was written against (server.py's APP_API); the dashboard's
// suite holds the two equal (test/appapi.mjs), so a dashboard change that
// moves the surface fails there until this app is updated with it, and
// the app, seeing a dashboard ahead of it, says so and points at the newer
// build. Bump both together, never one.
// Asked once, at configuration time. `bb` is on PATH inside BuilderBot and on
// its nodes; anywhere else the property the workflow passes is the answer,
// and "0.0.0-unknown" is the honest last resort rather than a number somebody
// would trust.
fun ask(vararg argv: String): String? = try {
    val pb = ProcessBuilder(*argv).directory(rootDir.parentFile).redirectErrorStream(false)
    pb.environment()["BB_RELAYED"] = "1"
    val p = pb.start()
    val out = p.inputStream.bufferedReader().readText().trim()
    if (p.waitFor() == 0 && out.isNotEmpty()) out else null
} catch (e: Exception) { null }

// BB_RELAYED, for the same reason the workflow sets it: from a checkout that
// is not a project the controller knows, an unset `bb version` tries to relay
// and answers nothing.
fun bb(what: String): String? =
    ask("bb", "version", what) ?: ask("bash", "scripts/bb", "version", what)

val bbVersion: String = (findProperty("bbVersion") as String?)?.takeIf { it.isNotBlank() }
    ?: bb("--semver") ?: "0.0.0-unknown"
val bbCode: Int = ((findProperty("bbCode") as String?)?.toIntOrNull()
    ?: bb("--code")?.toIntOrNull() ?: 1)

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.plugin.compose")
}

// The debug APK into dist/, under the name it is asked for (-PbbOut), from
// wherever this build wrote it: the build directory is off the share on a
// node (the root build file, B351), so a command copying from
// app/build/outputs would find nothing there.
tasks.register<Copy>("bbApk") {
    dependsOn("assembleDebug")
    from(layout.buildDirectory.dir("outputs/apk/debug"))
    include("app-debug.apk")
    into(rootDir.parentFile.resolve("dist"))
    rename { (findProperty("bbOut") as String?)?.takeIf { it.isNotBlank() } ?: it }
}

android {
    namespace = "dev.builderbot.app"
    compileSdk = 36

    defaultConfig {
        applicationId = "dev.builderbot.app"
        minSdk = 26
        targetSdk = 36
        versionCode = bbCode
        versionName = bbVersion
        buildConfigField("int", "TARGET_API", "9")
    }
    // A release has no signing config here, so Gradle writes it unsigned
    // (R106): BuilderBot signs it with the project's own sideload key, on the
    // controller for a release (releasesign.py) and with bb sign otherwise.
    // No key, alias or password is in the tree or in CI.
    buildTypes {
        release {
            isMinifyEnabled = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
    }
    buildFeatures {
        compose = true
        buildConfig = true
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

dependencies {
    // The newest set that compiles against android-36, which is the platform
    // the store carries. Compose 1.12 (BOM 2026.08 on), core 1.19, lifecycle
    // 2.11 and navigation 2.10 each want 37; read off their AAR metadata, so
    // when platform 37 lands on the store all four move together.
    val bom = platform("androidx.compose:compose-bom:2026.06.01")
    implementation(bom)
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.compose.material:material-icons-core")
    implementation("androidx.activity:activity-compose:1.13.0")
    implementation("androidx.navigation:navigation-compose:2.9.8")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.10.0")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.10.0")
    implementation("androidx.core:core-ktx:1.18.0")
    implementation("androidx.security:security-crypto:1.1.0")
    // The app's lock (R133): the phone's own fingerprint, face or PIN.
    implementation("androidx.biometric:biometric:1.1.0")
    // ...whose FragmentActivity must be a current one: the fragment library
    // biometric 1.1.0 carries rejects the request codes activity 1.13's
    // result registry hands out ("Can only use lower 16 bits", B493).
    implementation("androidx.fragment:fragment-ktx:1.8.9")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.11.0")
}
