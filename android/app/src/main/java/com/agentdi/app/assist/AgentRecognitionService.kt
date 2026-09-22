package com.agentdi.app.assist

import android.content.Intent
import android.speech.RecognitionService
import android.speech.SpeechRecognizer

/**
 * A stub RecognitionService. A VoiceInteractionService must name a recognition
 * service in its metadata, but Agent-Di does its speech-to-text server-side
 * (Sarvam ASR via the app), not through the system SpeechRecognizer. So this
 * declines cleanly; it exists only to satisfy the assistant registration.
 */
class AgentRecognitionService : RecognitionService() {
    override fun onStartListening(recognizerIntent: Intent?, listener: Callback?) {
        try { listener?.error(SpeechRecognizer.ERROR_CLIENT) } catch (_: Exception) {}
    }

    override fun onStopListening(listener: Callback?) {}

    override fun onCancel(listener: Callback?) {}
}
