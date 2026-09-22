package com.agentdi.app.notifications

/**
 * On-device filter for incoming messages. Mirrors the server's triage so that
 * non-VIP and OTP-like messages are dropped ON THE PHONE and never leave it —
 * only messages from people the user marked important are forwarded, and never
 * an OTP. This is the privacy-by-locality rule for the WhatsApp reader.
 */
object NotificationTriage {

    // "OTP is 123456", "code: 4821", "123456 is your ... code"
    private val otp = Regex(
        """\b(otp|code|one[\s-]?time)\b.*?\b\d{4,8}\b|\b\d{4,8}\b.*?\b(otp|code)\b""",
        RegexOption.IGNORE_CASE,
    )

    data class Summary(val isVip: Boolean, val shouldNotify: Boolean, val sender: String, val text: String)

    fun triage(sender: String, text: String, vips: Set<String>): Summary {
        val isOtp = otp.containsMatchIn(text)
        val isVip = vips.any { it.normalize() == sender.normalize() }
        val summary = if (isOtp) "" else text.collapseWhitespace().take(140)
        return Summary(isVip = isVip, shouldNotify = isVip && !isOtp, sender = sender, text = summary)
    }

    private fun String.normalize() = trim().replace(Regex("""\s+"""), " ").lowercase()
    private fun String.collapseWhitespace() = trim().replace(Regex("""\s+"""), " ")
}
