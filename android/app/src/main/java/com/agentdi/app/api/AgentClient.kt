package com.agentdi.app.api

import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.util.concurrent.TimeUnit

/**
 * Thin client for the Agent-Di app-service (the Python AppService exposed over
 * HTTP). The service is the source of truth for every action; the app only
 * renders cards and launches the UPI intent. All money still requires the
 * user's PIN inside their own UPI app.
 */
class AgentClient(private val baseUrl: String, private val authToken: String) {

    private val http = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .build()

    private val json = Json { ignoreUnknownKeys = true }

    @Serializable data class HandleRequest(val utterance: String)
    @Serializable data class ActionCard(
        val token: String,
        val title: String,
        val lines: List<String> = emptyList(),
        val total: String? = null,
        val authorization: String = "none",
        val upiUri: String? = null,
        val notes: List<String> = emptyList(),
    )
    @Serializable data class PlannedReply(val kind: String, val message: String, val card: ActionCard? = null)
    @Serializable data class SettleRequest(val token: String, val status: String, val txnRef: String? = null)
    @Serializable data class PaymentOutcome(val ok: Boolean, val message: String, val reference: String? = null)

    suspend fun handle(utterance: String): PlannedReply =
        post("/handle", json.encodeToString(HandleRequest.serializer(), HandleRequest(utterance)),
            PlannedReply.serializer())

    suspend fun settle(token: String, status: String, txnRef: String?): PaymentOutcome =
        post("/settle", json.encodeToString(SettleRequest.serializer(), SettleRequest(token, status, txnRef)),
            PaymentOutcome.serializer())

    /** The on-device notification reader forwards ONLY already-VIP, non-OTP summaries. */
    suspend fun forwardVipSummary(sender: String, summary: String) {
        post("/notifications/vip", """{"sender":${json.encodeToString(String.serializer(), sender)},""" +
            """"summary":${json.encodeToString(String.serializer(), summary)}}""", Unit.serializer())
    }

    private fun <T> post(path: String, body: String, deserializer: kotlinx.serialization.KSerializer<T>): T {
        val req = Request.Builder()
            .url(baseUrl.trimEnd('/') + path)
            .addHeader("Authorization", "Bearer $authToken")
            .post(body.toRequestBody("application/json".toMediaType()))
            .build()
        http.newCall(req).execute().use { resp ->
            val text = resp.body?.string().orEmpty()
            require(resp.isSuccessful) { "HTTP ${resp.code}: $text" }
            return json.decodeFromString(deserializer, text.ifEmpty { "{}" })
        }
    }
}
