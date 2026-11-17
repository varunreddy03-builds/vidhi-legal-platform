"""Evidence classification for neuroscience and audio-frequency claims (Phase 8). Pure code, no AI, no audio, no health advice.

Two jobs:
  * FRAMEWORK - the classes of evidence and the distinctions every answer in this area must keep apart (shown to the reader as-is).
  * SCREEN - find sentences that present an unsupported audio or brain-frequency claim as fact (guaranteed intelligence gains, "hidden powers", sound frequency equated with brain rhythm).
The framework text is orientation, not a literature review: it states no study results and no numbers except the commonly used band names, and it is marked unreviewed until a qualified person signs it off.
English wording only; rules are a net, not a proof."""

import re

REVIEWED = False  # flips only when a qualified reviewer has signed off the framework text; the API reports it

CLASSES = {
    "established_mechanism": "A mechanism supported by many independent, replicated lines of evidence (for example, that the brain produces measurable electrical oscillations).",
    "experimental_result": "A finding from a particular study or a small group of studies. It may be real but depends on sample size, design, replication and effect size.",
    "open_question": "Something researchers are still investigating or disagree about.",
    "commercial_claim": "A statement made to sell a product or programme. It is not evidence unless independent studies support it.",
    "unsupported_claim": "A claim with no good evidence, or one that contradicts what is known (guaranteed gains, hidden powers, supernatural abilities).",
}

DISTINCTIONS = [
    ("oscillations", "Brain electrical oscillations", "Rhythmic electrical activity in the brain that techniques such as EEG can measure. It is a property of the brain, not of a sound."),
    ("pitch", "Sound frequency and perceived pitch", "The frequency of a sound is a physical property of the air vibration. Pitch is how a listener perceives it. Neither is the same thing as the frequency of brain activity."),
    ("loudness", "Amplitude, intensity, loudness and exposure time", "How strong a sound is, how loud it seems and for how long someone hears it are separate things, and the last two matter for safety."),
    ("stimulation", "Binaural beats and other auditory stimulation", "Different methods with different proposed mechanisms. Whether and how they affect brain activity or behaviour is studied, with mixed and context-dependent results."),
    ("domains", "Sleep, attention, relaxation, learning and memory", "Separate research areas. A result in one does not carry over to another."),
    ("source", "Experimental results versus commercial claims", "Check who is making the statement, whether a study is cited, and whether independent work has replicated it."),
    ("settled", "Established mechanisms versus open questions", "Say which parts are well established and which are still being worked out."),
]

BANDS = {
    "note": "Band names are conventions. Their boundaries differ between papers, species, ages and recording methods, and the same name can mean slightly different ranges.",
    "names": ["delta", "theta", "alpha", "beta", "gamma"],
}

APPRAISAL = ["study design", "sample size", "replication by independent groups", "effect size, not only statistical significance", "limitations the authors state", "safety, including loudness and exposure time"]

LIMITS = [
    "Educational classification of claims. It is not medical advice and no audio is played or recommended.",
    "A claim being absent from this screen does not make it true.",
    "No study results are stated here; a source-backed reference collection must be loaded and reviewed first.",
]

_AUDIO = r"(?:binaural|isochronic|monaural|frequenc\w*|\bhz\b|\btones?\b|\bmusic\b|\baudio\b|\bsound\w*|\bbeats?\b|\bsongs?\b|\bplaylists?\b|\bsolfeggio\b|\bwaves?\b|\bentrainment\b|\bpitch\b)"
_GAIN = r"(?:increas\w*|boost\w*|rais\w*|improv\w*|unlock\w*|activat\w*|heal\w*|cur(?:e|es|ed)\b|enhanc\w*|rewir\w*|repair\w*|smarter|more intelligent|psychic|genius|(?:deep )?relaxation)"
_SURE = r"(?:will|always|guarantee\w*|automatically|instantly|overnight|definitely|permanently|forever|is proven|proven to|certain(?:ly)? to|never fails|makes?(?: everyone| you| anyone)?|gives?|is guaranteed)"
# (rule id, evidence class, pattern, why, safer wording)
RULES = [
    ("guaranteed_gain", "unsupported_claim", re.compile(rf"{_AUDIO}[^.\n]{{0,90}}\b{_SURE}\b[^.\n]{{0,70}}\b{_GAIN}|{_AUDIO}[^.\n]{{0,90}}\b{_GAIN}\b[^.\n]{{0,60}}\b(?:permanently|forever|guaranteed|always|instantly|overnight)\b", re.I),
     "Presents a guaranteed cognitive or health gain from sound.", "Some studies have examined whether it affects attention or relaxation; results are mixed."),
    ("intelligence", "unsupported_claim", re.compile(rf"{_AUDIO}[^.\n]{{0,90}}\b(?:IQ|genius|intelligence|smarter|more intelligent)\b", re.I),
     "Links a sound or frequency to intelligence without evidence.", "No good evidence shows that listening to a frequency raises intelligence."),
    ("hidden_powers", "unsupported_claim", re.compile(r"\b(?:unlock\w*|activat\w*|awaken\w*)\b[^.\n]{0,40}\b(?:hidden|dormant|latent|supernatural|psychic|third eye|pineal|dna|powers?)\b|\b(?:pineal|third eye)\b[^.\n]{0,40}\b(?:activat\w*|awaken\w*|open\w*)|\b(?:give|gives|grant|grants)\b[^.\n]{0,30}\b(?:supernatural|psychic)\b[^.\n]{0,20}\b(?:powers?|abilit\w+)", re.I),
     "Claims sound or frequency can unlock hidden or supernatural abilities.", "There is no scientific evidence for hidden or supernatural abilities being activated by sound."),
    ("magic_frequency", "commercial_claim", re.compile(r"\b(?:174|285|396|417|432|528|639|741|852|963)\s?hz\b[^.\n]{0,100}\b(?:heal\w*|dna|repair\w*|miracle|cure\w*|detox\w*|frequency of (?:love|god))", re.I),
     "Attaches healing or DNA effects to a specific tone, a typical commercial claim.", "Specific 'healing frequencies' are marketing claims; independent evidence for them is lacking."),
    ("frequency_healing", "commercial_claim", re.compile(r"\b(?:frequency|sound|solfeggio|tone) healing\b|\bsolfeggio frequenc\w+[^.\n]{0,40}\b(?:repair\w*|heal\w*|cur\w*)", re.I),
     "Presents frequency or sound healing as established.", "'Frequency healing' is a marketing term; independent evidence for it is lacking."),
    ("sound_equals_brain", "unsupported_claim", re.compile(r"\b(?:brain|neurons?|brainwaves?)\b[^.\n]{0,50}\b(?:will|always|automatically|simply)\b[^.\n]{0,30}\b(?:match\w*|sync\w*|follow\w*|copy|copies|mirror\w*)\b[^.\n]{0,40}\b(?:sound|tone|frequenc\w*|beat\w*|rhythm|music|song)|\bbrain ?waves?\b[^.\n]{0,40}\b(?:changed|set|controlled|determined|driven)\b[^.\n]{0,15}\bdirectly\b[^.\n]{0,30}\b(?:pitch|frequenc\w*|sound|song|music)", re.I),
     "Treats the frequency of a sound as if it directly sets the frequency of brain activity.", "Whether and how brain rhythms follow an external rhythm (entrainment) is an open research question."),
]
_HEDGE = re.compile(r"\b(?:no (?:good |reliable |scientific )?evidence|little evidence|limited evidence|weak evidence|no (?:study|studies|research|trial|trials)|\bno\b[^.]{0,30}\bcan\b|not (?:supported|proven|established|true)|unproven|myth|misconception|claim(?:s|ed)?|market(?:ed|ing)|advertis\w*|asserts?|supposedly|allegedly|may|might|could|whether|hypothes\w*|some studies|studies? (?:have )?(?:examined|tested|looked)|open question|is not|are not|does not|do not|cannot|can't)\b", re.I)
_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")


def screen_sentence(sentence: str) -> dict | None:
    """The first unsupported-claim rule a sentence trips, or None. Hedged, reported or denied statements are left alone."""
    if _HEDGE.search(sentence):
        return None
    for rule, cls, rx, why, safer in RULES:
        if rx.search(sentence):
            return {"rule": rule, "class": cls, "why": why, "safer": safer}
    return None


def classify(text: str) -> list[dict]:
    """Every sentence of `text` that trips a rule, with its class, why and a safer wording."""
    out = []
    for s in _SPLIT.split(text or ""):
        hit = screen_sentence(s) if s.strip() else None
        if hit:
            out.append({"sentence": s.strip()[:300], **hit})
    return out


def framework() -> dict:
    return {"classes": [{"id": k, "meaning": v} for k, v in CLASSES.items()], "distinctions": [{"id": i, "title": t, "note": n} for i, t, n in DISTINCTIONS],
            "bands": BANDS, "appraise_studies_by": APPRAISAL, "reviewed": REVIEWED, "limits": LIMITS}
