package com.agentdi.app.pay

import android.content.Intent
import android.net.Uri

/**
 * Launches the user's own UPI app with a pre-filled payment, and parses the
 * result. The agent never sees or enters the PIN — the user completes the
 * payment inside their UPI app, exactly as if they'd typed it themselves.
 */
object UpiHandoff {

    /** Build a chooser Intent for a upi:// link produced by the app-service. */
    fun intentFor(upiUri: String): Intent {
        val intent = Intent(Intent.ACTION_VIEW, Uri.parse(upiUri))
        return Intent.createChooser(intent, "Pay with UPI")
    }

    data class Result(val status: String, val txnRef: String?)

    /**
     * Parse the response a UPI app returns in the Activity result. The response
     * is a `key=value&...` string with `Status` (SUCCESS/FAILURE/SUBMITTED) and,
     * on success, a transaction ref (`txnId`/`txnRef`). Absent/unknown → FAILURE.
     */
    fun parseResult(data: Intent?): Result {
        val raw = data?.getStringExtra("response").orEmpty()
        if (raw.isBlank()) return Result("FAILURE", null)
        val fields = raw.split("&").mapNotNull {
            val i = it.indexOf('='); if (i <= 0) null else it.substring(0, i).lowercase() to it.substring(i + 1)
        }.toMap()
        val status = fields["status"]?.uppercase() ?: "FAILURE"
        val ref = fields["txnid"] ?: fields["txnref"]
        return Result(status, ref?.takeIf { it.isNotBlank() })
    }
}
