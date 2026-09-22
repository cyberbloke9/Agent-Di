package com.agentdi.app

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.agentdi.app.api.AgentClient
import com.agentdi.app.ui.ApprovalCardScreen
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class MainActivity : ComponentActivity() {
    private val client by lazy { AgentClient(Config.BASE_URL, Config.AUTH_TOKEN) }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme {
                Surface(Modifier.fillMaxSize()) { AgentScreen(client) }
            }
        }
    }
}

@Composable
fun AgentScreen(client: AgentClient) {
    var input by remember { mutableStateOf("") }
    var status by remember { mutableStateOf("Ask me to pay a bill, shop, or source something.") }
    var card by remember { mutableStateOf<AgentClient.ActionCard?>(null) }
    val scope = rememberCoroutineScope()

    Column(
        Modifier.fillMaxSize().padding(16.dp).verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("Agent-Di", style = MaterialTheme.typography.headlineSmall)
        OutlinedTextField(
            value = input,
            onValueChange = { input = it },
            label = { Text("What do you need?") },
            modifier = Modifier.fillMaxWidth(),
        )
        Button(
            modifier = Modifier.fillMaxWidth(),
            onClick = {
                val utterance = input
                scope.launch {
                    status = "Thinking…"
                    card = null
                    try {
                        val reply = withContext(Dispatchers.IO) { client.handle(utterance) }
                        status = reply.message
                        card = reply.card
                    } catch (e: Exception) {
                        status = "Error: ${e.message}"
                    }
                }
            },
            enabled = input.isNotBlank(),
        ) { Text("Ask") }

        Text(status)

        card?.let { c ->
            ApprovalCardScreen(
                card = c,
                onSettled = { outcome ->
                    status = outcome.message
                    card = null
                },
                settle = { token, s, ref -> withContext(Dispatchers.IO) { client.settle(token, s, ref) } },
                scope = scope,
            )
        }
    }
}
