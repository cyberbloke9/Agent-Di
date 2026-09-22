"""BBPS (Bharat Bill Payment System) bill payments.

Billers come from the user's saved profile (SYSTEM), never from the model. The
bill amount fetched from BBPS is untrusted, so a one-off payment always needs
the user's PIN. Where the user has registered BBPS AutoPay (a bank-executed
e-mandate), the agent only detects and informs the user — it never auto-debits.
"""

from agentdi.bills.agent import BillPayAgent, BillPaymentProposal
from agentdi.bills.bbps import BbpsGateway, Bill, BillReceipt, FakeBbps
from agentdi.bills.billers import Biller, BillerBook, resolve

__all__ = [
    "BbpsGateway",
    "Bill",
    "BillPayAgent",
    "BillPaymentProposal",
    "BillReceipt",
    "Biller",
    "BillerBook",
    "FakeBbps",
    "resolve",
]
