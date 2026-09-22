"""The app-facing service layer: one interface the Android/iOS app calls.

It ties the engines (planner, bills, commerce, policy, journal) together and
returns serializable DTOs the app renders — approval cards, the UPI hand-off,
notification summaries. All money still flows through the policy engine and the
user's PIN; the app only renders and launches the UPI intent.
"""

from agentdi.app.dto import (
    ActionCard,
    Authorization,
    NotificationSummary,
    PaymentOutcome,
    PlannedReply,
    UpiResult,
)
from agentdi.app.service import AppService

__all__ = [
    "ActionCard",
    "AppService",
    "Authorization",
    "NotificationSummary",
    "PaymentOutcome",
    "PlannedReply",
    "UpiResult",
]
