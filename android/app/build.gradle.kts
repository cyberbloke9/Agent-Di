plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
}

android {
    namespace = "com.agentdi.app"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.agentdi.app"
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "0.1"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
}

// No external dependencies on purpose: pure Android SDK (Views, HttpURLConnection,
// org.json), so the app builds fully offline. Networking/JSON/UPI all use the
// framework; the Kotlin stdlib is added automatically by the Kotlin plugin.
dependencies {
}
