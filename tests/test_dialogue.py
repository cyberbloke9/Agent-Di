from agentdi.calling import CallBrief, RfqDialogue, Slot
from agentdi.calling.disclosure import disclosure

BRIEF = CallBrief(
    company_name="Agent-Di",
    user_name="Prithvi",
    product="transparent cups",
    specs="different sizes, transparent PET",
    quantity="500",
    by_when="Friday",
)


def drive(dialogue, replies):
    """Return (agent_lines, final_quote). Feeds scripted vendor replies until done."""
    lines = []
    step = dialogue.opening()
    lines.append(step.say)
    for r in replies:
        assert not step.done, "dialogue ended before replies were exhausted"
        step = dialogue.step(r)
        lines.append(step.say)
        if step.done:
            return lines, step.quote
    # drive to completion with silence if not done
    while not step.done:
        step = dialogue.step(None)
        lines.append(step.say)
    return lines, step.quote


def test_opening_always_discloses_ai_and_recording():
    step = RfqDialogue(BRIEF, "v1", "Acme Packaging").opening()
    assert disclosure("Agent-Di", "Prithvi") in step.say
    assert "AI assistant" in step.say and "recorded" in step.say
    assert step.expecting is Slot.YES_NO


def test_happy_path_collects_a_usable_quote():
    replies = [
        "yes we supply transparent cups",
        "yes we have all sizes, minimum order 100 pieces",
        "it's about 6 rupees per cup",
        "yes we can deliver by Friday",
        "yes that's right",
    ]
    lines, quote = drive(RfqDialogue(BRIEF, "v1", "Acme Packaging"), replies)
    assert quote.available is True
    assert quote.unit_price_text and "6" in quote.unit_price_text
    assert quote.can_meet_deadline is True
    assert quote.min_order_text and "100" in quote.min_order_text
    assert quote.needs_user is False and quote.usable is True
    # read-back names the user and refuses to order on the call
    assert any("won't place the order on this call" in ln for ln in lines)


def test_vendor_does_not_supply():
    _, quote = drive(RfqDialogue(BRIEF, "v2", "Random Store"), ["no, we don't have that"])
    assert quote.available is False and quote.usable is False


def test_vendor_wants_account_holder_hands_back_to_user():
    _, quote = drive(RfqDialogue(BRIEF, "v3", "Cagey Traders"), ["who is this? I need to speak to the account holder"])
    assert quote.needs_user is True and quote.usable is False
    assert "directly" in quote.ended_reason


def test_never_commits_money_when_vendor_pushes_for_payment():
    replies = [
        "yes we supply",
        "yes all sizes",
        "12 rupees each but you must pay a booking amount by UPI now",  # payment push mid-call
        "yes deliver by Friday",
        "yes correct",
    ]
    lines, quote = drive(RfqDialogue(BRIEF, "v4", "Pushy Packaging"), replies)
    assert quote.needs_user is True  # flagged for the user
    assert any("can't confirm any payment on this call" in ln.lower() or "can't confirm any payment" in ln for ln in lines)
    # it still gathered the quote rather than committing
    assert quote.unit_price_text is not None


def test_silence_ends_the_call_needing_the_user():
    d = RfqDialogue(BRIEF, "v5", "Silent Co")
    d.opening()
    step = d.step(None)
    assert step.done and step.quote.needs_user is True


def test_turn_cap_ends_the_call():
    d = RfqDialogue(BRIEF, "v6", "Rambler Traders", max_turns=3)
    d.opening()
    step = None
    for _ in range(6):
        step = d.step("hmm well let me think about it and check with my team")
        if step.done:
            break
    assert step.done and step.quote.needs_user is True


def test_delivery_unclear_is_recorded_not_guessed():
    replies = [
        "yes we supply",
        "yes all sizes",
        "10 rupees each",
        "maybe, I will have to check the truck schedule",
        "yes correct",
    ]
    _, quote = drive(RfqDialogue(BRIEF, "v7", "Maybe Movers"), replies)
    assert quote.can_meet_deadline is None
    assert any("delivery unclear" in n for n in quote.notes)


def test_extra_questions_are_asked_and_recorded():
    brief = BRIEF.model_copy(update={"extra_questions": ("Do you provide GST invoice?",)})
    replies = [
        "yes we supply",
        "yes all sizes",
        "8 rupees each",
        "yes by Friday",
        "yes we give GST invoice",  # answer to the extra question
        "yes correct",  # readback
    ]
    lines, quote = drive(RfqDialogue(brief, "v8", "Proper Traders"), replies)
    assert any("GST invoice" in ln for ln in lines)
    assert any("GST invoice" in n for n in quote.notes)
    assert quote.usable is True
