"""The code-level net under the strategy, reasoning and behaviour analyses: unsupported diagnosis, guaranteed-strategy claims, invented probabilities and certain-intent claims are removed
and reported; explanations of concepts, hedged sentences and numbers the person supplied are left alone."""

import pytest

from lib.analysis_guard import clean_text, clean_tree


@pytest.mark.parametrize("sentence,rule", [
    ("He is a psychopath and will not change.", "diagnosis"),
    ("Your boss has narcissistic personality disorder.", "diagnosis"),
    ("She appears to be bipolar given her messages.", "diagnosis"),
    ("This person is clearly a sociopath.", "diagnosis"),
    ("This approach always works against a stronger opponent.", "universal"),
    ("A guaranteed way to win the negotiation is to delay.", "universal"),
    ("It is a foolproof tactic.", "universal"),
    ("There is a 70% chance they will settle.", "probability"),
    ("The probability of success is 0.8.", "probability"),
    ("They are clearly lying about the delivery.", "motive"),
    ("He is manipulating you into paying.", "motive"),
    ("She clearly intends to delay the payment.", "motive"),
])
def test_each_unsafe_kind_of_sentence_is_removed_and_reported(sentence, rule):
    text, flags = clean_text(f"A first sentence is fine. {sentence} A last sentence is fine.")
    assert [f["rule"] for f in flags] == [rule]
    assert sentence not in text and "[Removed by VIDHI:" in text and "A first sentence is fine." in text and "A last sentence is fine." in text


@pytest.mark.parametrize("sentence", [
    "Narcissism is a personality construct studied in research, and it is not a diagnosis of any one person.",
    "Psychopathy checklists are used by trained clinicians in specific settings.",
    "Machiavellianism describes a strategic, manipulative orientation in the research literature.",
    "I cannot diagnose him, and a label like narcissist should not be applied from messages alone.",
    "Negotiators often delay, which may signal either difficulty or tactics.",
    "A delay could be a tactic, or it could be a cash-flow problem.",
    "This option has risks that depend on how the other side responds.",
])
def test_explanations_hedged_sentences_and_ordinary_advice_are_left_alone(sentence):
    text, flags = clean_text(sentence)
    assert text == sentence and flags == []


def test_numbers_the_person_supplied_are_allowed_but_new_ones_are_not():
    given = "My supplier says there is a 30% chance the goods arrive late; invoice is Rs 40,000."
    assert clean_text("You noted a 30% chance of delay.", given)[1] == []
    assert [f["rule"] for f in clean_text("So the chance of delay is really 55%.", given)[1]] == ["probability"]
    assert clean_text("The invoice of Rs 40,000 is due in 15 days.", given)[1] == []  # amounts and days are not probabilities


def test_the_tree_walker_cleans_every_string_and_collects_every_removal():
    reply = {"summary": "He is a psychopath.", "options": [{"idea": "It always works.", "risks": ["Delay is possible."]}], "n": 3, "ok": True}
    flags: list = []
    out = clean_tree(reply, flags=flags)
    assert sorted(f["rule"] for f in flags) == ["diagnosis", "universal"]
    assert out["options"][0]["risks"] == ["Delay is possible."] and out["n"] == 3 and out["ok"] is True
    assert "[Removed by VIDHI:" in out["summary"] and "[Removed by VIDHI:" in out["options"][0]["idea"]


def test_non_english_text_is_not_screened_and_says_nothing_false():
    telugu = "అతను ఒక మానసిక రోగి"
    assert clean_text(telugu) == (telugu, [])
