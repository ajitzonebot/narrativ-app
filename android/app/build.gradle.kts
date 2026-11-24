import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
    id("org.jetbrains.kotlin.plugin.serialization")
}

val vProps = Properties().apply { rootProject.file("version.properties").inputStream().use { load(it) } }
val apiProps = Properties().apply { rootProject.file("api.properties").takeIf { it.exists() }?.inputStream()?.use { load(it) } }
val vCode = (project.findProperty("versionCode") as String?)?.toInt() ?: 1
val vName = (project.findProperty("versionName") as String?) ?: vProps.getProperty("versionName")

android {
    namespace = "com.narrativ.app"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.narrativ.app"
        minSdk = 26
        targetSdk = 35
        versionCode = vCode
        versionName = vName
        // API base URL is written by the worker-deploy workflow; empty = read the public repo directly
        buildConfigField("String", "API_URL", "\"${apiProps.getProperty("apiUrl", "")}\"")
    }

    signingConfigs {
        create("release") {
            // Keystore never lives in the repo: CI decodes it from the NARRATIV_KEYSTORE_B64 secret.
            System.getenv("NARRATIV_KEYSTORE")?.let { storeFile = file(it) }
            storePassword = System.getenv("NARRATIV_KS_PASS")
            keyAlias = "narrativ"
            keyPassword = System.getenv("NARRATIV_KS_PASS")
        }
    }

    buildTypes {
        debug {
            buildConfigField("String", "APP_KEY", "\"narrativ-app\"")  // dummy for debug and CI screenshots
        }
        release {
            // No key in release builds: the APK is public. The owner types the key once (AccessKey.kt).
            buildConfigField("String", "APP_KEY", "\"\"")
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName("release")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    buildFeatures { compose = true; buildConfig = true }
}


dependencies {
    val bom = platform("androidx.compose:compose-bom:2024.12.01")
    implementation(bom)
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.activity:activity-compose:1.9.3")
    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.work:work-runtime-ktx:2.9.1")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.7.3")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")
    testImplementation("junit:junit:4.13.2")
}
