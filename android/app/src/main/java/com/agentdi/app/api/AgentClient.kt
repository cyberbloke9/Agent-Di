package com.agentdi.app.api

import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/**
 * Client for the Agent-Di app-service, using only the Android SDK
 * (HttpURLConnection + org.json) so the app has no external dependencies. The
 * service is the source of truth for every action; the app only renders cards
 * and launches the UPI intent. All money still requires the user's PIN inside
 * their own UPI app. Call these off the main thread.
 */
class AgentClient(private val baseUrl: String, private val authToken: String) {

    data class ActionCard(
        val token: String,
        val title: String,
        val lines: List<String>,
        val total: String?,
        val authorization: String,
        val upiUri: String?,
        val notes: List<String>,
    )

    data class PlannedReply(val kind: String, val message: String, val card: ActionCard?)

    data class PaymentOutcome(val ok: Boolean, val message: String, val reference: String?)

    fun handle(utterance: String): PlannedReply {
        val res = post("/handle", JSONObject().put("utterance", utterance).toString())
        val cardObj = res.optJSONObject("card")
        val card = if (cardObj == null) null else ActionCard(
            token = cardObj.optString("token"),
            title = cardObj.optString("title"),
            lines = cardObj.optJSONArray("lines").toStringList(),
            total = cardObj.stringOrNull("total"),
            authorization = cardObj.optString("authorization", "none"),
            upiUri = cardObj.stringOrNull("upiUri"),
            notes = cardObj.optJSONArray("notes").toStringList(),
        )
        return PlannedReply(res.optString("kind"), res.optString("message"), card)
    }

    fun settle(token: String, status: String, txnRef: String?): PaymentOutcome {
        val body = JSONObject().put("token", token).put("status", status)
        if (txnRef != null) body.put("txnRef", txnRef)
        val res = post("/settle", body.toString())
        return PaymentOutcome(res.optBoolean("ok"), res.optString("message"), res.stringOrNull("reference"))
    }

    /** The on-device notification reader forwards ONLY already-VIP, non-OTP summaries. */
    fun forwardVipSummary(sender: String, summary: String) {
        post("/notifications/vip", JSONObject().put("sender", sender).put("summary", summary).toString())
    }

    /**
     * Upload recorded WAV audio to the server's Sarvam ASR and get the transcript.
     * `lang` is an optional BCP-47 hint (e.g. "hi-IN", "te-IN"); null lets Sarvam
     * auto-detect. Runs off the main thread. The transcript is only ever placed in
     * the input box for the user to review — it never authorises anything by itself.
     */
    fun transcribe(wav: ByteArray, lang: String?): String {
        val path = if (lang.isNullOrBlank()) "/transcribe" else "/transcribe?lang=$lang"
        val conn = (URL(baseUrl.trimEnd('/') + path).openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            connectTimeout = 15000
            readTimeout = 60000
            doOutput = true
            setRequestProperty("Content-Type", "audio/wav")
            setRequestProperty("Authorization", "Bearer $authToken")
        }
        conn.outputStream.use { it.write(wav) }
        val code = conn.responseCode
        val stream = if (code in 200..299) conn.inputStream else conn.errorStream
        val text = stream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() }.orEmpty()
        conn.disconnect()
        if (code !in 200..299) throw RuntimeException("HTTP $code: $text")
        return JSONObject(text).optString("text")
    }

    private fun post(path: String, body: String): JSONObject {
        val conn = (URL(baseUrl.trimEnd('/') + path).openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            connectTimeout = 15000
            readTimeout = 40000
            doOutput = true
            setRequestProperty("Content-Type", "application/json")
            setRequestProperty("Authorization", "Bearer $authToken")
        }
        conn.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
        val code = conn.responseCode
        val stream = if (code in 200..299) conn.inputStream else conn.errorStream
        val text = stream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() }.orEmpty()
        conn.disconnect()
        if (code !in 200..299) throw RuntimeException("HTTP $code: $text")
        return if (text.isBlank()) JSONObject() else JSONObject(text)
    }
}

private fun JSONArray?.toStringList(): List<String> =
    if (this == null) emptyList() else (0 until length()).map { optString(it) }

private fun JSONObject.stringOrNull(key: String): String? =
    if (!has(key) || isNull(key)) null else optString(key)
