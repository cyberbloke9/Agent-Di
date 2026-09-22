"""The mandatory opening disclosure for an AI call.

India's synthetic-content rules require a human-sounding AI voice to announce
itself up front, and we never impersonate the user. Every outbound call opens
with this, in the vendor's language where known.
"""

from __future__ import annotations

_TEMPLATES = {
    "en": "Hello, this is an AI assistant from {company}, calling on behalf of {user}. This call is recorded. ",
    "hi": "नमस्ते, मैं {company} का AI सहायक हूँ, {user} की ओर से कॉल कर रहा हूँ। यह कॉल रिकॉर्ड हो रही है। ",
    "te": "నమస్తే, నేను {company} అనే AI సహాయకుడిని, {user} తరఫున కాల్ చేస్తున్నాను. ఈ కాల్ రికార్డ్ అవుతోంది. ",
}


def disclosure(company: str, user: str, lang: str = "en") -> str:
    """The opening line. `user` is a first name only, never the full identity."""
    template = _TEMPLATES.get(lang, _TEMPLATES["en"])
    return template.format(company=company, user=user)
