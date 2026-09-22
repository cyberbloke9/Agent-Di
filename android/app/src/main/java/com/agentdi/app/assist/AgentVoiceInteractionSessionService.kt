package com.agentdi.app.assist

import android.os.Bundle
import android.service.voice.VoiceInteractionSession
import android.service.voice.VoiceInteractionSessionService

/** Creates a fresh [AgentVoiceInteractionSession] each time the assist gesture fires. */
class AgentVoiceInteractionSessionService : VoiceInteractionSessionService() {
    override fun onNewSession(args: Bundle?): VoiceInteractionSession =
        AgentVoiceInteractionSession(this)
}
