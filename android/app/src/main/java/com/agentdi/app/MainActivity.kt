package com.agentdi.app

import android.Manifest
import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import android.speech.RecognizerIntent
import android.view.ViewGroup.LayoutParams.MATCH_PARENT
import android.view.ViewGroup.LayoutParams.WRAP_CONTENT
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import com.agentdi.app.api.AgentClient
import com.agentdi.app.audio.Recorder
import com.agentdi.app.pay.UpiHandoff
import java.util.Locale
import kotlin.concurrent.thread

/**
 * A dependency-free Views UI: type OR speak a request, see the reply and (for a
 * payment) an approval card whose "Pay with UPI" button hands off to the user's
 * UPI app. Voice uses the system speech recognizer (no extra deps, and it asks
 * for the mic itself). The agent never sees the PIN; settle() runs only on the
 * UPI result.
 */
class MainActivity : Activity() {

    private val client by lazy { AgentClient(Config.BASE_URL, Config.AUTH_TOKEN) }
    private lateinit var input: EditText
    private lateinit var status: TextView
    private lateinit var cardBox: LinearLayout
    private lateinit var recordBtn: Button
    private var pending: AgentClient.ActionCard? = null
    private var recorder: Recorder? = null

    private val UPI_REQUEST = 1001
    private val VOICE_REQUEST = 1002
    private val MIC_REQUEST = 1003

    companion object {
        const val EXTRA_UTTERANCE = "com.agentdi.app.UTTERANCE"
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(48, 72, 48, 48)
        }
        val title = TextView(this).apply { text = "Agent-Di"; textSize = 26f }
        input = EditText(this).apply { hint = "What do you need?" }

        val buttons = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        val ask = Button(this).apply { text = "Ask" }
        val mic = Button(this).apply { text = "🎤 Speak" }
        recordBtn = Button(this).apply { text = "● Record" }
        buttons.addView(ask, LinearLayout.LayoutParams(0, WRAP_CONTENT, 1f))
        buttons.addView(mic, LinearLayout.LayoutParams(0, WRAP_CONTENT, 1f))
        buttons.addView(recordBtn, LinearLayout.LayoutParams(0, WRAP_CONTENT, 1f))

        status = TextView(this).apply {
            text = "Type, use 🎤 Speak (on-device), or ● Record for accurate Hindi/Telugu."
            setPadding(0, 32, 0, 0)
        }
        cardBox = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(0, 32, 0, 0)
        }
        // Opens the system "Digital assistant app" picker so the user can set
        // Agent-Di as their default assistant (then the assist gesture — long-press
        // home / power — launches it over any app, like the Assistant slot).
        val assistantBtn = Button(this).apply {
            text = "Enable as phone assistant"
            setOnClickListener { openAssistantSettings() }
        }
        listOf(title, input, buttons, status, cardBox, assistantBtn).forEach {
            root.addView(it, LinearLayout.LayoutParams(MATCH_PARENT, WRAP_CONTENT))
        }
        setContentView(ScrollView(this).apply { addView(root) })

        ask.setOnClickListener { ask(input.text.toString().trim()) }
        mic.setOnClickListener { startVoice() }
        recordBtn.setOnClickListener { toggleRecord() }

        // The assistant session forwards its utterance here so the audited
        // approval-card + UPI-PIN + settle flow runs in the Activity, never in
        // the overlay session (design rule: money stays in the audited path).
        intent?.getStringExtra(EXTRA_UTTERANCE)?.trim()?.let { if (it.isNotEmpty()) { input.setText(it); ask(it) } }
    }

    private fun openAssistantSettings() {
        // VOICE_INPUT_SETTINGS is where the "Digital assistant app" chooser lives.
        val actions = listOf("android.settings.VOICE_INPUT_SETTINGS", android.provider.Settings.ACTION_SETTINGS)
        for (a in actions) {
            try { startActivity(Intent(a)); return } catch (_: Exception) {}
        }
        status.text = "Open Settings > Apps > Default apps > Digital assistant app, and pick Agent-Di."
    }

    /**
     * Tap to record, tap again to stop. On stop the WAV goes to the server's
     * Sarvam ASR (accurate Indic transcription) — this is the fix for the
     * on-device recognizer mistranslating Hindi/Telugu. The transcript only
     * fills the input box; nothing is authorised without the usual approval card.
     */
    private fun toggleRecord() {
        val r = recorder
        if (r != null && r.isRecording) {
            recordBtn.text = "● Record"
            status.text = "Transcribing…"
            r.stop()  // the worker thread finishes, transcribes, and updates the UI
            return
        }
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), MIC_REQUEST)
            return
        }
        startRecording()
    }

    private fun startRecording() {
        val rec = Recorder()
        recorder = rec
        recordBtn.text = "■ Stop"
        status.text = "Recording… tap Stop when done."
        thread {
            try {
                val wav = rec.start()  // blocks until stop()
                val text = client.transcribe(wav, null)  // null = let Sarvam auto-detect the language
                runOnUiThread {
                    recorder = null
                    recordBtn.text = "● Record"
                    if (text.isNotBlank()) {
                        input.setText(text)
                        ask(text)
                    } else {
                        status.text = "Didn't catch that. Try again."
                    }
                }
            } catch (e: Exception) {
                runOnUiThread {
                    recorder = null
                    recordBtn.text = "● Record"
                    status.text = "Error: ${e.message}"
                }
            }
        }
    }

    private fun startVoice() {
        val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            putExtra(RecognizerIntent.EXTRA_LANGUAGE, Locale.getDefault().toLanguageTag())
            putExtra(RecognizerIntent.EXTRA_PROMPT, "Speak your request (English, Hindi, Telugu…)")
        }
        try {
            @Suppress("DEPRECATION")
            startActivityForResult(intent, VOICE_REQUEST)
        } catch (e: ActivityNotFoundException) {
            status.text = "No speech recognizer on this device. Type instead."
        }
    }

    private fun ask(utterance: String) {
        if (utterance.isEmpty()) return
        status.text = "Thinking…"
        cardBox.removeAllViews()
        pending = null
        thread {
            try {
                val reply = client.handle(utterance)
                runOnUiThread {
                    status.text = reply.message
                    reply.card?.let { showCard(it) }
                }
            } catch (e: Exception) {
                runOnUiThread { status.text = "Error: ${e.message}" }
            }
        }
    }

    private fun showCard(card: AgentClient.ActionCard) {
        pending = card
        cardBox.removeAllViews()
        val lines = buildString {
            append(card.title).append('\n')
            card.lines.forEach { append(it).append('\n') }
            card.total?.let { append("Total: ").append(it).append('\n') }
            card.notes.forEach { append(it).append('\n') }
        }
        cardBox.addView(TextView(this).apply { text = lines })
        if (card.authorization == "upi_pin" && card.upiUri != null) {
            cardBox.addView(Button(this).apply {
                text = "Pay with UPI"
                setOnClickListener {
                    @Suppress("DEPRECATION")
                    startActivityForResult(UpiHandoff.intentFor(card.upiUri), UPI_REQUEST)
                }
            })
        }
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == MIC_REQUEST) {
            if (grantResults.firstOrNull() == PackageManager.PERMISSION_GRANTED) {
                startRecording()
            } else {
                status.text = "Mic permission needed to record. You can still type or use 🎤 Speak."
            }
        }
    }

    @Deprecated("Deprecated in Java")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        when (requestCode) {
            VOICE_REQUEST -> {
                if (resultCode == RESULT_OK) {
                    val heard = data?.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS)?.firstOrNull().orEmpty()
                    if (heard.isNotEmpty()) {
                        input.setText(heard)
                        ask(heard)
                    }
                }
            }
            UPI_REQUEST -> {
                val card = pending ?: return
                val result = UpiHandoff.parseResult(data)
                status.text = "Confirming…"
                thread {
                    try {
                        val outcome = client.settle(card.token, result.status, result.txnRef)
                        runOnUiThread {
                            status.text = outcome.message
                            cardBox.removeAllViews()
                            pending = null
                        }
                    } catch (e: Exception) {
                        runOnUiThread { status.text = "Error: ${e.message}" }
                    }
                }
            }
        }
    }
}
