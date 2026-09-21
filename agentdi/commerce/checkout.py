"""From one approved cart to orders.

The approval card is what the user taps once. After that, each store's order
goes through the policy engine: inside a mandate it is paid from the user's
pre-set cap; otherwise the user's UPI app opens for their PIN. Every step is
journaled.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from agentdi.commerce.engine import PlanOutcome
from agentdi.commerce.models import CartPlan
from agentdi.commerce.registry import MerchantRegistry
from agentdi.core import ActionKind, Channel, Intent, Money, Source
from agentdi.journal import Journal
from agentdi.payments import UpiIntent, build_upi_intent
from agentdi.policy import Auth, Decision, PolicyContext, PolicyEngine, Verdict


class ApprovalCard(BaseModel):
    model_config = ConfigDict(frozen=True)

    headline: str
    lines: tuple[str, ...]
    stores: tuple[str, ...]
    total: Money
    eta_minutes: int | None
    notes: tuple[str, ...]


def build_approval_card(
    outcome: PlanOutcome, registry: MerchantRegistry, preferred_store: str | None = None, plan_index: int = 0
) -> ApprovalCard:
    plan = outcome.plans[plan_index]
    names = {m.id: m.display_name for m in registry.all()}
    lines, notes = [], []
    for basket in plan.baskets:
        store = names[basket.store_id]
        for line in basket.lines:
            lines.append(f"{store} · {line.offer.title} × {line.item.qty} · {line.cost}")
            if preferred_store and basket.store_id != preferred_store:
                notes.append(f"{line.item.label()} wasn't available at {names[preferred_store]}, so it comes from {store}.")
        fee = "free delivery" if basket.delivery_fee.paise == 0 else f"delivery {basket.delivery_fee}"
        lines.append(f"{store} · {fee}")
    notes += [f"No connected store has {item.label()}." for item in plan.missing]
    for store_id, url in outcome.handoffs().items():
        notes.append(f"{names[store_id]} has no official API; open it yourself: {url}")
    etas = [b.eta_minutes for b in plan.baskets if b.eta_minutes is not None]
    count = sum(len(b.lines) for b in plan.baskets)
    stores = tuple(names[s] for s in plan.store_ids)
    return ApprovalCard(
        headline=f"{count} item{'s' if count != 1 else ''} from {len(stores)} store{'s' if len(stores) != 1 else ''}",
        lines=tuple(lines),
        stores=stores,
        total=plan.total,
        eta_minutes=max(etas) if etas else None,
        notes=tuple(dict.fromkeys(notes)),
    )


class OrderStatus(StrEnum):
    PAID_WITHIN_MANDATE = "paid_within_mandate"
    AWAITING_PIN = "awaiting_pin"
    DENIED = "denied"


class OrderStep(BaseModel):
    model_config = ConfigDict(frozen=True)

    store_id: str
    intent_id: str
    amount: Money
    decision: Decision
    status: OrderStatus
    upi: UpiIntent | None = None


class Checkout:
    def __init__(self, policy: PolicyEngine, registry: MerchantRegistry, journal: Journal) -> None:
        self.policy = policy
        self.registry = registry
        self.journal = journal

    def run(
        self, plan: CartPlan, ctx: PolicyContext, channel: Channel = Channel.APP, category: str = "groceries"
    ) -> list[OrderStep]:
        self.journal.append(
            "checkout.approved",
            {"stores": list(plan.store_ids), "total_paise": plan.total.paise, "channel": channel.value},
            ctx.now,
        )
        steps = []
        for basket in plan.baskets:
            merchant = self.registry.get(basket.store_id)
            intent = Intent(
                kind=ActionKind.PLACE_ORDER,
                description=f"Order from {merchant.display_name}",
                counterparty=merchant.as_counterparty(),
                counterparty_source=Source.SYSTEM,
                amount=basket.total,
                amount_source=Source.PARTNER_API,
                category=category,
                channel=channel,
            )
            decision = self.policy.evaluate(intent, ctx)
            self.journal.append(
                "policy.decision",
                {
                    "intent_id": intent.id, "store": merchant.id, "amount_paise": basket.total.paise,
                    "verdict": decision.verdict.value, "auth": decision.auth.value,
                    "reasons": list(decision.reasons), "mandate_id": decision.mandate_id,
                },
                ctx.now,
            )
            steps.append(self._act(intent, decision, basket.total, merchant.id, ctx))
        return steps

    def _act(self, intent: Intent, decision: Decision, amount: Money, store_id: str, ctx: PolicyContext) -> OrderStep:
        merchant = self.registry.get(store_id)
        if decision.allowed and decision.mandate_id:
            ctx.ledger.record(decision.mandate_id, amount, ctx.now)
            self.journal.append(
                "payment.mandate_debit",
                {"intent_id": intent.id, "store": store_id, "amount_paise": amount.paise, "mandate_id": decision.mandate_id},
                ctx.now,
            )
            return OrderStep(store_id=store_id, intent_id=intent.id, amount=amount, decision=decision,
                             status=OrderStatus.PAID_WITHIN_MANDATE)
        if decision.verdict is Verdict.CONFIRM and decision.auth is Auth.UPI_PIN:
            upi = build_upi_intent(
                merchant.vpa, merchant.display_name, amount, intent.id, f"Agent-Di order {intent.id[:8]}", Source.SYSTEM
            )
            self.journal.append(
                "payment.upi_intent",
                {"intent_id": intent.id, "store": store_id, "amount_paise": amount.paise, "uri": upi.uri()},
                ctx.now,
            )
            return OrderStep(store_id=store_id, intent_id=intent.id, amount=amount, decision=decision,
                             status=OrderStatus.AWAITING_PIN, upi=upi)
        return OrderStep(store_id=store_id, intent_id=intent.id, amount=amount, decision=decision,
                         status=OrderStatus.DENIED)
