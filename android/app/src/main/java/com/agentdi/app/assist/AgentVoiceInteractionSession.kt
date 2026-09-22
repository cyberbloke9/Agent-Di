package com.agentdi.app.assist

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.service.voice.VoiceInteractionSession
import android.view.View
import android.view.ViewGroup.LayoutParams.MATCH_PARENT
import android.view.ViewGroup.LayoutParams.WRAP_CONTENT
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import com.agentdi.app.Config
import com.agentdi.app.MainActivity
import com.agentdi.app.api.AgentClient
import com.agentdi.app.audio.Recorder
import kotlin.concurrent.thread

/**
 * The assistant overlay shown on the assist gesture. A compact version of the main
 * chat: type or (if the mic is already granted) record a request, see the reply.
 *
 * It deliberately does NOT move money. If the reply is a payment card, it hands the
 * request off to [MainActivity] via startAssistantActivity, so the approval card,
 * UPI-PIN hand-off and settle round-trip happen only in the audited Activity flow
 * (design rule: money stays in the audited path, never in this overlay). Runtime
 * permission requests aren't possible from a session, so voice here works only when
 * RECORD_AUDIO was granted earlier in the app; otherwise it points the user there.
 */
class AgentVoiceInteractionSession(context: Context) : VoiceInteractionSession(context) {

    private val client by lazy { AgentClient(Config.BASE_URL, Config.AUTH_TOKEN) }
    private val main = Handler(Looper.getMainLooper())
    private lateinit var input: EditText
    private lateinit var status: TextView
    private lateinit var cardView: TextView
    private lateinit var completeBtn: Button
    private lateinit var recordBtn: Button
    private var recorder: Recorder? = null
    private var pendingUtterance: String? = null

    override fun onCreateContentView(): View {
        val ctx = context
        val root = LinearLayout(ctx).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(48, 48, 48, 48)
            setBackgroundColor(0xFFFFFFFF.toInt())
        }
        val title = TextView(ctx).apply { text = "Agent-Di"; textSize = 22f }
        input = EditText(ctx).apply { hint = "What do you need?" }

        val row = LinearLayout(ctx).apply { orientation = LinearLayout.HORIZONTAL }
        val ask = Button(ctx).apply { text = "Ask" }
        recordBtn = Button(ctx).apply { text = "● Record" }
        val close = Button(ctx).apply { text = "Close" }
        row.addView(ask, LinearLayout.LayoutParams(0, WRAP_CONTENT, 1f))
        row.addView(recordBtn, LinearLayout.LayoutParams(0, WRAP_CONTENT, 1f))
        row.addView(close, LinearLayout.LayoutParams(0, WRAP_CONTENT, 1f))

        status = TextView(ctx).apply { text = "Ask for a bill, shopping or sourcing."; setPadding(0, 24, 0, 0) }
        cardView = TextView(ctx).apply { setPadding(0, 24, 0, 0); visibility = View.GONE }
        completeBtn = Button(ctx).apply {
            text = "Complete in Agent-Di"
            visibility = View.GONE
            setOnClickListener { handOffToApp() }
        }

        listOf(title, input, row, status, cardView, completeBtn).forEach {
            root.addView(it, LinearLayout.LayoutParams(MATCH_PARENT, WRAP_CONTENT))
        }

        ask.setOnClickListener { ask(input.text.toString().trim()) }
        recordBtn.setOnClickListener { toggleRecord() }
        close.setOnClickListener { hide() }
        return root
    }

    private fun ask(utterance: String) {
        if (utterance.isEmpty()) return
        status.text = "Thinking…"
        cardView.visibility = View.GONE
        completeBtn.visibility = View.GONE
        pendingUtterance = null
        thread {
            try {
                val reply = client.handle(utterance)
                main.post {
                    status.text = reply.message
                    val card = reply.card
                    if (card != null) {
                        // A payment/approval card: don't authorise here — send it to the app.
                        pendingUtterance = utterance
                        cardView.text = buildString {
                            append(card.title).append('\n')
                            card.lines.forEach { append(it).append('\n') }
                            card.total?.let { append("Total: ").append(it) }
                        }
                        cardView.visibility = View.VISIBLE
                        if (card.authorization == "upi_pin") completeBtn.visibility = View.VISIBLE
                    }
                }
            } catch (e: Exception) {
                main.post { status.text = "Error: ${e.message}" }
            }
        }
    }

    private fun handOffToApp() {
        val u = pendingUtterance ?: return
        val intent = Intent(context, MainActivity::class.java).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            putExtra(MainActivity.EXTRA_UTTERANCE, u)
        }
        startAssistantActivity(intent)  // launch the audited app flow to pay with the PIN
        hide()
    }

    private fun toggleRecord() {
        val r = recorder
        if (r != null && r.isRecording) {
            recordBtn.text = "● Record"
            status.text = "Transcribing…"
            r.stop()
            return
        }
        if (context.checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            status.text = "Open Agent-Di once and allow the mic to use voice here. Typing works now."
            return
        }
        val rec = Recorder()
        recorder = rec
        recordBtn.text = "■ Stop"
        status.text = "Recording… tap Stop when done."
        thread {
            try {
                val wav = rec.start()
                val text = client.transcribe(wav, null)
                main.post {
                    recorder = null
                    recordBtn.text = "● Record"
                    if (text.isNotBlank()) { input.setText(text); ask(text) }
                    else status.text = "Didn't catch that. Try again."
                }
            } catch (e: Exception) {
                main.post { recorder = null; recordBtn.text = "● Record"; status.text = "Error: ${e.message}" }
            }
        }
    }

    override fun onShow(args: Bundle?, showFlags: Int) {
        super.onShow(args, showFlags)
        // If the OS handed us a spoken/typed query with the assist, run it straight away.
        val q = args?.getString("query")?.trim()
            ?: args?.getString(Intent.EXTRA_TEXT)?.trim()
        if (!q.isNullOrEmpty()) { input.setText(q); ask(q) }
    }
}
