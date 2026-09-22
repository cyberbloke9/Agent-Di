package com.agentdi.app.ui

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.agentdi.app.api.AgentClient
import com.agentdi.app.pay.UpiHandoff
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch

/**
 * Renders one approval card from the app-service and, when it needs the UPI PIN,
 * launches the user's UPI app. On the result the app calls settle() — the agent
 * never sees the PIN.
 */
@Composable
fun ApprovalCardScreen(
    card: AgentClient.ActionCard,
    onSettled: (AgentClient.PaymentOutcome) -> Unit,
    settle: suspend (token: String, status: String, txnRef: String?) -> AgentClient.PaymentOutcome,
    scope: CoroutineScope,
) {
    val launcher = rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        val parsed = UpiHandoff.parseResult(result.data)
        scope.launch {
            onSettled(settle(card.token, parsed.status, parsed.txnRef))
        }
    }

    Card(Modifier.fillMaxWidth().padding(16.dp)) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(card.title, style = androidx.compose.material3.MaterialTheme.typography.titleMedium)
            card.lines.forEach { Text(it) }
            card.total?.let { Text("Total: $it") }
            card.notes.forEach { Text(it, style = androidx.compose.material3.MaterialTheme.typography.bodySmall) }

            if (card.authorization == "upi_pin" && card.upiUri != null) {
                Button(onClick = { launcher.launch(UpiHandoff.intentFor(card.upiUri)) }, Modifier.fillMaxWidth()) {
                    Text("Pay with UPI")
                }
            }
        }
    }
}
