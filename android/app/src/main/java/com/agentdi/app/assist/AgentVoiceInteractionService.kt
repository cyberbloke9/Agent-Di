package com.agentdi.app.assist

import android.service.voice.VoiceInteractionService

/**
 * Registers Agent-Di as a selectable **default digital assistant** on Android.
 *
 * Once the user picks Agent-Di in Settings > Apps > Default apps > Digital
 * assistant app, the assist gesture (long-press home / power-button hold, per the
 * device) starts a session — [AgentVoiceInteractionSession] — over whatever app is
 * on screen, exactly the Assistant slot. This service itself holds no logic; the
 * metadata in res/xml/interaction_service.xml points the framework at the session
 * and (stub) recognition service. There is no wake word: invocation is the
 * gesture, not "Hey Agent-Di" (a hotword needs an always-on engine we don't ship).
 */
class AgentVoiceInteractionService : VoiceInteractionService()
