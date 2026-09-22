package com.agentdi.app

/**
 * Where the app finds the Agent-Di app-service, and the dev auth token.
 *
 * For a USB-connected phone, run on the desktop:
 *   adb reverse tcp:8000 tcp:8000
 * so the phone's `localhost:8000` reaches the desktop server. For LAN instead,
 * set BASE_URL to the desktop's IP, e.g. "http://192.168.1.20:8000".
 */
object Config {
    const val BASE_URL = "http://localhost:8000"
    const val AUTH_TOKEN = "dev-token"
}
