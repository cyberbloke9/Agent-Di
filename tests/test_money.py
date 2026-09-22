import pytest

from agentdi.core import Money


def test_rupees_to_paise():
    assert Money.rupees("49.50").paise == 4950
    assert Money.rupees(10).paise == 1000
    assert Money.rupees("0.005").paise == 1  # half-up


def test_float_refused():
    with pytest.raises(TypeError):
        Money.rupees(49.5)


def test_bool_refused():
    with pytest.raises(TypeError):
        Money.rupees(True)
    with pytest.raises(TypeError):
        Money.rupees(1) * True


@pytest.mark.parametrize("bad", ["Infinity", "-Infinity", "NaN", "1e1000"])
def test_non_finite_and_out_of_range_refused(bad):
    with pytest.raises(ValueError):
        Money.rupees(bad)


def test_negative_refused():
    with pytest.raises(ValueError):
        Money(paise=-1)


def test_arithmetic_and_ordering():
    a, b = Money.rupees(100), Money.rupees("25.25")
    assert (a + b).paise == 12525
    assert (a - b).paise == 7475
    assert (b * 3).paise == 7575
    assert b < a and a >= b


def test_formats():
    assert str(Money.rupees("1234567.5")) == "₹12,34,567.50"
    assert str(Money.rupees(999)) == "₹999.00"
    assert Money.rupees("7.05").to_upi_amount() == "7.05"
