// Versions in one place. AGP carries Kotlin itself since 9.0, so there is
// no kotlin.android plugin to pin; the Compose compiler is Kotlin's own
// plugin since 2.0, and its version is the Kotlin AGP bundles.
plugins {
    id("com.android.application") version "9.4.1" apply false
    id("org.jetbrains.kotlin.plugin.compose") version "2.4.20" apply false
}
