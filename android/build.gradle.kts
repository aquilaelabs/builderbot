// Versions in one place. AGP and Kotlin move together; the Compose compiler
// is Kotlin's own plugin since 2.0, so there is no separate version for it.
plugins {
    id("com.android.application") version "8.10.1" apply false
    id("org.jetbrains.kotlin.android") version "2.1.21" apply false
    id("org.jetbrains.kotlin.plugin.compose") version "2.1.21" apply false
}
