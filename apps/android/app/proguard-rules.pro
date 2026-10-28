# Nothing reflective in this app; the defaults hold. org.json is a platform class.

# Tink (under androidx.security's EncryptedSharedPreferences) names
# compile-time annotations that are not on the runtime classpath; R8 stops on
# them as missing classes, which broke every release build once the biometric
# lock's dependencies arrived (B508, 5 Oct). They are annotations only.
-dontwarn com.google.errorprone.annotations.**
-dontwarn javax.annotation.**
