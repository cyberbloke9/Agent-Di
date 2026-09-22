"""Data classification and the train-eligibility gate (design rule 6).

Every piece of data the agent stores carries a classification and a
`train_eligible` flag that defaults to False. Nothing may be used to train a
model unless the user opted in AND the data is the user's own, non-sensitive
data. This makes the privacy-by-default rule enforceable, not just documented,
for the ingestion pipeline that will consume it.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class DataClass(StrEnum):
    USER_OWN = "user_own"
    """The user's own content (their notes, their preferences)."""

    THIRD_PARTY = "third_party"
    """Data about other people (a contact's message, a call transcript)."""

    SENSITIVE = "sensitive"
    """Credentials, payment, health, biometric — never trainable, ever."""

    CHILD = "child"
    """Data of a user who is (or may be) under 18."""


# Only the user's own, non-sensitive data can ever be training-eligible.
_TRAINABLE_CLASSES = frozenset({DataClass.USER_OWN})


class Tagged(BaseModel):
    """Mixin for any stored record. Fail-closed: not trainable unless earned."""

    model_config = ConfigDict(frozen=True)

    data_class: DataClass
    train_eligible: bool = Field(default=False)
    user_opted_in_to_training: bool = False


def may_train(record: Tagged) -> bool:
    """The single gate every training pipeline must call. All conditions required."""
    return (
        record.train_eligible
        and record.user_opted_in_to_training
        and record.data_class in _TRAINABLE_CLASSES
    )
