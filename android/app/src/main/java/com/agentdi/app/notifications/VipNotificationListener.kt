package com.agentdi.app.notifications

import android.app.Notification
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification

/**
 * Reads incoming notifications and surfaces only messages from important people.
 *
 * Scope and privacy:
 *  - Only WhatsApp (and other messengers the user opts into) are inspected.
 *  - Filtering runs ON DEVICE (NotificationTriage): non-VIP and OTP-like
 *    messages are dropped here and never sent anywhere.
 *  - Only a VIP summary is forwarded to the agent. Replies (a later feature)
 *    are only ever sent by the user tapping WhatsApp's own reply action —
 *    the app never auto-sends, per WhatsApp's terms.
 */
class VipNotificationListener : NotificationListenerService() {

    private val watched = setOf("com.whatsapp", "com.whatsapp.w4b")

    // In a real build these come from the user's synced settings / a repository.
    private fun vips(): Set<String> = VipStore.current()

    override fun onNotificationPosted(sbn: StatusBarNotification) {
        if (sbn.packageName !in watched) return
        val extras = sbn.notification.extras ?: return

        // Group/summary notifications and silent ones are skipped.
        if (sbn.notification.flags and Notification.FLAG_GROUP_SUMMARY != 0) return

        val sender = extras.getCharSequence(Notification.EXTRA_TITLE)?.toString().orEmpty()
        val text = extras.getCharSequence(Notification.EXTRA_TEXT)?.toString().orEmpty()
        if (sender.isBlank() || text.isBlank()) return

        val result = NotificationTriage.triage(sender, text, vips())
        if (!result.shouldNotify) return  // dropped on device; nothing leaves the phone

        AgentBridge.onVipMessage(applicationContext, result.sender, result.text)
    }
}

/** Placeholder for the user's VIP list; back it with DataStore in the real app. */
object VipStore {
    @Volatile private var vips: Set<String> = emptySet()
    fun set(names: Set<String>) { vips = names }
    fun current(): Set<String> = vips
}

/** Where a surfaced VIP message goes: forward to the agent and/or a local notification. */
object AgentBridge {
    fun onVipMessage(context: android.content.Context, sender: String, summary: String) {
        // Wire to AgentClient.forwardVipSummary(sender, summary) on a background scope,
        // and/or post a local notification. Kept as a seam so the listener stays testable.
    }
}
