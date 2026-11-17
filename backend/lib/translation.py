"""Translating an approved notice without changing what it says.

An AI writes the translated wording; code protects the parts that must not change:
  * the statement of account and the list of enclosures are lifted out before translation and put back unchanged
    (English), so no figure is ever re-typed by a model;
  * afterwards, every number in the English notice, and every party name and the invoice number, must appear in the
    translation exactly as written, or the translation is flagged and cannot be sent;
  * a translation belongs to ONE English version. If the English changes, the translation is stale and unusable.
The English text stays the authoritative notice; the translation is a courtesy copy and says so."""

import re

from lib.languages import LANGUAGE_NAMES

# All 22 languages of the Eighth Schedule. A translation is never sent until a person fluent in that language has read it
# and ticked the box (see routers/recovery_translation.py); the code still guards every figure and name.
LANGUAGES = {code: name for code, name in LANGUAGE_NAMES.items() if code != "en"}

STATEMENT_MARK, ENCLOSURE_MARK = "{{STATEMENT}}", "{{ENCLOSURES}}"
_BLOCK = {
    STATEMENT_MARK: re.compile(r"(?m)^Statement of account\n(?:[ \t]+.*\n?)+"),
    ENCLOSURE_MARK: re.compile(r"(?m)^Enclosures\n(?:[ \t]+.*\n?)+"),
}
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")

COURTESY = {
    "en": "Translation (courtesy copy). The English notice is the authoritative text.",
    "hi": "अनुवाद (सुविधा हेतु प्रति)। अंग्रेज़ी नोटिस ही प्रामाणिक पाठ है।",
    "mr": "भाषांतर (सोयीसाठी प्रत). इंग्रजी नोटीस हाच अधिकृत मजकूर आहे.",
    "gu": "અનુવાદ (સુવિધા માટેની નકલ). અંગ્રેજી નોટિસ જ અધિકૃત લખાણ છે.",
    "bn": "অনুবাদ (সুবিধার জন্য প্রতিলিপি)। ইংরেজি নোটিসই প্রামাণ্য পাঠ।",
    "ta": "மொழிபெயர்ப்பு (வசதிக்கான நகல்). ஆங்கில அறிவிப்பே அதிகாரப்பூர்வ உரை.",
    "te": "అనువాదం (సౌలభ్యం కోసం ప్రతి). ఆంగ్ల నోటీసే ప్రామాణిక పాఠం.",
    "kn": "ಅನುವಾದ (ಅನುಕೂಲಕ್ಕಾಗಿ ಪ್ರತಿ). ಇಂಗ್ಲಿಷ್ ನೋಟಿಸ್ ಅಧಿಕೃತ ಪಠ್ಯ.",
    "ml": "വിവർത്തനം (സൗകര്യത്തിനുള്ള പകർപ്പ്). ഇംഗ്ലീഷ് നോട്ടീസാണ് ആധികാരിക പാഠം.",
    "pa": "ਅਨੁਵਾਦ (ਸਹੂਲਤ ਲਈ ਕਾਪੀ)। ਅੰਗਰੇਜ਼ੀ ਨੋਟਿਸ ਹੀ ਪ੍ਰਮਾਣਿਕ ਪਾਠ ਹੈ।",
    "ur": "ترجمہ (سہولت کے لیے نقل)۔ انگریزی نوٹس ہی مستند متن ہے۔",
    "or": "ଅନୁବାଦ (ସୁବିଧା ପାଇଁ ନକଲ)। ଇଂରାଜୀ ନୋଟିସ୍ ହିଁ ପ୍ରାମାଣିକ ପାଠ।",
    "as": "অনুবাদ (সুবিধাৰ বাবে প্ৰতিলিপি)। ইংৰাজী নোটিচখনেই প্ৰামাণিক পাঠ।",
    "ne": "अनुवाद (सुविधाका लागि प्रतिलिपि)। अङ्ग्रेजी सूचना नै प्रामाणिक पाठ हो।",
    "mai": "अनुवाद (सुविधाक लेल प्रति)। अंग्रेजी नोटिसे प्रामाणिक पाठ अछि।",
    "kok": "भाशांतर (सोयी खातीर प्रत). इंग्लीश नोटीस हो अधिकृत मजकूर.",
    "sa": "अनुवादः (सौकर्यार्थं प्रतिलिपिः)। आङ्ग्लसूचना एव प्रामाणिकः पाठः।",
    "doi": "अनुवाद (सुविधा आस्तै कापी)। अंग्रेजी नोटिस गै प्रामाणिक पाठ ऐ।",
    "sd": "ترجمو (سهولت لاءِ نقل). انگريزي نوٽيس ئي مستند متن آهي.",
}


def lift_blocks(english: str) -> tuple[str, dict[str, str]]:
    """Replace the code-written statement and enclosure blocks with markers; return the text and the blocks."""
    kept: dict[str, str] = {}
    text = english
    for mark, rx in _BLOCK.items():
        m = rx.search(text)
        if m:
            kept[mark] = m.group(0).rstrip("\n")
            text = text[: m.start()] + mark + "\n" + text[m.end():]
    return text, kept


def restore_blocks(translated: str, kept: dict[str, str]) -> str:
    for mark, block in kept.items():
        if mark in translated:
            translated = translated.replace(mark, block)
        else:  # the model dropped the marker: put the block back at the end rather than lose the figures
            translated = translated.rstrip() + "\n\n" + block
    return translated


def numbers_in(text: str) -> list[str]:
    return [n.rstrip(",") for n in _NUMBER.findall(text)]


def preservation_check(english: str, translated: str, protected: list[str]) -> dict:
    """What the translation failed to preserve. `protected` = names/numbers that must appear verbatim (party names, invoice no.)."""
    from lib.notice_checks import find_legal_references, find_placeholders, find_risky_language, find_service_claims, _without

    low = translated.lower()
    have, had = set(numbers_in(translated)), set(numbers_in(english))
    missing_numbers = sorted(had - have)  # whole numbers, not pieces of other numbers: a "15" must not be satisfied by the 15 inside an amount
    extra_numbers = sorted(have - had)
    missing_names = [p for p in protected if p and p.lower() in english.lower() and p.lower() not in low]
    scan = _without(translated, protected)
    problems: list[str] = []
    if not translated.strip():
        problems.append("The translation is empty.")
    if missing_numbers:
        problems.append("These numbers from the English notice are missing or changed: " + ", ".join(missing_numbers[:12]) + ".")
    if extra_numbers:
        problems.append("These numbers are in the translation but not in the English notice: " + ", ".join(extra_numbers[:12]) + ".")
    for label, found in (("words that threaten or accuse", find_risky_language(scan)), ("legal references", find_legal_references(scan)),
                         ("blanks left unfilled", find_placeholders(translated)), ("wording that says the notice was served or received", find_service_claims(scan))):
        if found:
            problems.append(f"The translation contains {label}: " + ", ".join(found[:5]) + ".")
    if missing_names:
        problems.append("These names or references must appear exactly as written: " + ", ".join(missing_names) + ".")
    return {"ok": not problems, "missing_numbers": missing_numbers, "extra_numbers": extra_numbers, "missing_names": missing_names, "problems": problems}
