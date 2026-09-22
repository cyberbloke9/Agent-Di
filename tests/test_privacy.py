import pytest

from agentdi.privacy import DataClass, Tagged, may_train


def rec(**kw):
    base = dict(data_class=DataClass.USER_OWN, train_eligible=True, user_opted_in_to_training=True)
    base.update(kw)
    return Tagged(**base)


def test_default_is_not_trainable():
    # Fail-closed: a record with only its class set is not trainable.
    assert may_train(Tagged(data_class=DataClass.USER_OWN)) is False


def test_all_conditions_required_to_train():
    assert may_train(rec()) is True
    assert may_train(rec(train_eligible=False)) is False
    assert may_train(rec(user_opted_in_to_training=False)) is False


@pytest.mark.parametrize("cls", [DataClass.THIRD_PARTY, DataClass.SENSITIVE, DataClass.CHILD])
def test_only_user_own_data_is_ever_trainable(cls):
    # Even fully opted-in and flagged, non-user-own data can never be trained on.
    assert may_train(rec(data_class=cls)) is False
