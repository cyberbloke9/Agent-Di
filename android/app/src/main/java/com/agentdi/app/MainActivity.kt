package com.agentdi.app

import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.Intent
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
    private var pending: AgentClient.ActionCard? = null

    private val UPI_REQUEST = 1001
    private val VOICE_REQUEST = 1002

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
        buttons.addView(ask, LinearLayout.LayoutParams(0, WRAP_CONTENT, 1f))
        buttons.addView(mic, LinearLayout.LayoutParams(0, WRAP_CONTENT, 1f))

        status = TextView(this).apply {
            text = "Ask or speak: pay a bill, shop, or source something."
            setPadding(0, 32, 0, 0)
        }
        cardBox = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(0, 32, 0, 0)
        }
        listOf(title, input, buttons, status, cardBox).forEach {
            root.addView(it, LinearLayout.LayoutParams(MATCH_PARENT, WRAP_CONTENT))
        }
        setContentView(ScrollView(this).apply { addView(root) })

        ask.setOnClickListener { ask(input.text.toString().trim()) }
        mic.setOnClickListener { startVoice() }
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
