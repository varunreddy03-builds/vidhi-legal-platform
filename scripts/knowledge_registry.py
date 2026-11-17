"""Builds docs/knowledge_registry.json and docs/VIDHI_KNOWLEDGE_REGISTRY.md from the table below (the owner's master list, numbered 1 to 50).

    python scripts/knowledge_registry.py          # rewrite both files

A REGISTRY ENTRY IS NOT CONTENT. Every entry starts at status "Registered". A later status needs a non-empty `evidence` field (a file hash, a licence, a test result): the validator in
backend/tests/test_knowledge_registry.py refuses anything else. `rights_hint` is the builder's UNVERIFIED first impression, kept apart from `rights_status` (which only a person's
check can change). Authors and titles come from the owner's list; editions, years and translators are deliberately left empty until checked against a real copy or catalogue."""

import json
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent / "docs"
DATA = Path(__file__).resolve().parent.parent / "backend" / "data" / "knowledge"  # shipped with the app; docs/ is not
STATUSES = ["Registered", "Source not yet located", "Source located", "Rights not yet verified", "Authorized for ingestion", "Ingestion pending", "Ingested", "Indexed",
            "Retrieval verified", "Evaluation passed", "Unavailable or blocked"]
HINTS = {
    "in_copyright": "Modern work: assume in copyright. No full-text indexing without a licence.",
    "public_domain_candidate": "Underlying work is old; the EDITION/TRANSLATION must be checked before it counts.",
    "official_government_text": "Official text; conditions of reuse must be read.",
    "us_gov_work_candidate": "Published by a government agency; reuse terms must be read.",
    "licence_required": "In copyright, reference work: needs a licence for any indexing.",
    "mixed_check_each_edition": "Old translations may be free; modern complete editions are not.",
}
# number, id, title, authors, section, kind, rights_hint
W = [
    (1, "48-laws-of-power", "The 48 Laws of Power", "Robert Greene", "A", "book", "in_copyright"),
    (2, "laws-of-human-nature", "The Laws of Human Nature", "Robert Greene", "A", "book", "in_copyright"),
    (3, "the-prince", "The Prince", "NiccolÃ² Machiavelli", "A", "book", "public_domain_candidate"),
    (4, "the-black-swan", "The Black Swan", "Nassim Nicholas Taleb", "A", "book", "in_copyright"),
    (5, "thinking-fast-and-slow", "Thinking, Fast and Slow", "Daniel Kahneman", "A", "book", "in_copyright"),
    (6, "mans-search-for-meaning", "Man's Search for Meaning", "Viktor E. Frankl", "A", "book", "in_copyright"),
    (7, "interpretation-of-dreams", "The Interpretation of Dreams", "Sigmund Freud", "A", "book", "public_domain_candidate"),
    (8, "archetypes-collective-unconscious", "The Archetypes and the Collective Unconscious", "Carl Gustav Jung", "A", "book", "in_copyright"),
    (9, "influence-psychology-of-persuasion", "Influence: The Psychology of Persuasion", "Robert B. Cialdini", "A", "book", "in_copyright"),
    (10, "art-of-war-sun-tzu", "The Art of War", "Sun Tzu", "A", "book", "public_domain_candidate"),
    (11, "beyond-good-and-evil", "Beyond Good and Evil", "Friedrich Nietzsche", "A", "book", "public_domain_candidate"),
    (12, "moby-dick", "Moby-Dick", "Herman Melville", "A", "book", "public_domain_candidate"),
    (13, "the-republic", "The Republic", "Plato", "A", "book", "public_domain_candidate"),
    (14, "leviathan", "Leviathan", "Thomas Hobbes", "A", "book", "public_domain_candidate"),
    (15, "meditations", "Meditations", "Marcus Aurelius", "A", "book", "public_domain_candidate"),
    (16, "corpus-juris-civilis", "Corpus Juris Civilis", "Compilation of Roman law associated with Justinian I", "A", "legal-text", "public_domain_candidate"),
    (17, "code-of-hammurabi", "The Code of Hammurabi", "Ancient Babylonian legal code", "A", "legal-text", "public_domain_candidate"),
    (18, "magna-carta", "Magna Carta", "Historical English charter", "A", "legal-text", "public_domain_candidate"),
    (19, "federalist-papers", "The Federalist Papers", "Alexander Hamilton, James Madison, John Jay", "A", "book", "public_domain_candidate"),
    (20, "blacks-law-dictionary", "Black's Law Dictionary", "Legal reference work", "A", "reference", "licence_required"),
    (21, "arthashastra", "Arthashastra", "Traditionally attributed to Kautilya", "B", "book", "public_domain_candidate"),
    (22, "bhagavad-gita", "Bhagavad Gita", "Hindu philosophical scripture", "B", "scripture", "public_domain_candidate"),
    (23, "constitution-of-india", "The Constitution of India", "Constituent Assembly of India", "B", "legal-text", "official_government_text"),
    (24, "demon-haunted-world", "The Demon-Haunted World", "Carl Sagan", "B", "book", "in_copyright"),
    (25, "superforecasting", "Superforecasting", "Philip E. Tetlock and Dan Gardner", "B", "book", "in_copyright"),
    (26, "the-prince-machiavelli-collection", "The Prince (Machiavelli collection entry)", "NiccolÃ² Machiavelli", "C", "collection-entry", "public_domain_candidate"),
    (27, "discourses-on-livy", "Discourses on Livy", "NiccolÃ² Machiavelli", "C", "book", "public_domain_candidate"),
    (28, "art-of-war-machiavelli", "The Art of War", "NiccolÃ² Machiavelli", "C", "book", "public_domain_candidate"),
    (29, "florentine-histories", "Florentine Histories", "NiccolÃ² Machiavelli", "C", "book", "public_domain_candidate"),
    (30, "letters-of-machiavelli", "The Letters of NiccolÃ² Machiavelli", "NiccolÃ² Machiavelli", "C", "book", "mixed_check_each_edition"),
    (31, "dark-triad-of-personality", "The Dark Triad of Personality", "Minna Lyons", "D", "book", "in_copyright"),
    (32, "without-conscience", "Without Conscience", "Robert D. Hare", "D", "book", "in_copyright"),
    (33, "snakes-in-suits", "Snakes in Suits: When Psychopaths Go to Work", "Paul Babiak and Robert D. Hare", "D", "book", "in_copyright"),
    (34, "in-sheeps-clothing", "In Sheep's Clothing: Understanding and Dealing with Manipulative People", "George K. Simon", "D", "book", "in_copyright"),
    (35, "laws-of-human-nature-darktriad-collection", "The Laws of Human Nature (Dark Triad collection entry)", "Robert Greene", "D", "collection-entry", "in_copyright"),
    (36, "causality-pearl", "Causality: Models, Reasoning, and Inference", "Judea Pearl", "E", "book", "in_copyright"),
    (37, "psychology-of-intelligence-analysis", "Psychology of Intelligence Analysis", "Richards J. Heuer Jr.", "E", "book", "us_gov_work_candidate"),
    (38, "the-scout-mindset", "The Scout Mindset", "Julia Galef", "E", "book", "in_copyright"),
    (39, "thinking-in-bets", "Thinking in Bets", "Annie Duke", "E", "book", "in_copyright"),
    (40, "strategy-of-conflict", "The Strategy of Conflict", "Thomas C. Schelling", "E", "book", "in_copyright"),
    (41, "noise-kahneman", "Noise: A Flaw in Human Judgment", "Daniel Kahneman, Olivier Sibony, Cass R. Sunstein", "E", "book", "in_copyright"),
    (42, "the-brain-that-changes-itself", "The Brain That Changes Itself", "Norman Doidge", "E", "book", "in_copyright"),
    (43, "behave-sapolsky", "Behave: The Biology of Humans at Our Best and Worst", "Robert M. Sapolsky", "E", "book", "in_copyright"),
    (44, "mindware", "Mindware: Tools for Smart Thinking", "Richard E. Nisbett", "E", "book", "in_copyright"),
    (45, "thinking-in-systems", "Thinking in Systems", "Donella H. Meadows", "E", "book", "in_copyright"),
    (46, "game-theory-tadelis", "Game Theory: An Introduction", "Steven Tadelis", "E", "book", "in_copyright"),
    (47, "how-to-think-about-weird-things", "How to Think About Weird Things", "Theodore Schick Jr. and Lewis Vaughn", "E", "book", "in_copyright"),
    (48, "thinking-like-a-lawyer", "Thinking Like a Lawyer", "Frederick Schauer", "E", "book", "in_copyright"),
    (49, "the-signal-and-the-noise", "The Signal and the Noise", "Nate Silver", "E", "book", "in_copyright"),
    (50, "the-coming-wave", "The Coming Wave", "Mustafa Suleyman and Michael Bhaskar", "E", "book", "in_copyright"),
]
SECTIONS = {"A": "Power, psychology, strategy and philosophy", "B": "Indian philosophy, law, governance and critical thinking", "C": "Dedicated Machiavelli collection",
            "D": "Dark Triad and manipulation awareness", "E": "Strategy, reasoning, neuroscience and future technology"}
CANONICAL = {26: 3, 35: 2}  # the same work listed again inside a collection: one source record, no second indexing
COLLECTIONS = {"machiavelli": [26, 27, 28, 29, 30], "dark_triad": [31, 32, 33, 34, 35]}
PHASES = {  # which later phase of the master prompt may use each work (planning only; nothing is used until authorised)
    5: [1, 2, 3, 27, 10, 28, 29, 30, 9, 40, 46, 39, 4, 25, 45], 6: [5, 4, 24, 25, 36, 37, 38, 39, 41, 44, 45, 49, 47],
    7: [2, 9, 5, 7, 8, 31, 32, 33, 34, 43, 42, 6, 11, 15], 8: [43, 42, 5, 7, 8, 24, 47],
    9: [6, 11, 13, 14, 15, 22, 21, 3, 27, 12, 19, 18, 16, 17], 10: [23, 20, 21, 16, 17, 18, 19, 13, 14, 48, 3, 27], 12: [50, 25, 4, 49, 36, 45, 46, 37, 24],
}


def build() -> dict:
    entries = []
    for n, slug, title, authors, sec, kind, hint in W:
        e = {
            "number": n, "id": slug, "title": title, "authors": authors, "section": sec, "kind": kind,
            "status": "Registered", "evidence": "",
            "source_status": "not_located", "rights_status": "not_verified", "rights_hint": hint,
            "edition": None, "translator": None, "year": None, "bibliographic_check": "from the owner's list only; not checked against a catalogue",
            "canonical_of": CANONICAL.get(n), "collections": [c for c, nums in COLLECTIONS.items() if n in nums],
            "planned_for_phases": sorted(p for p, nums in PHASES.items() if n in nums),
        }
        entries.append(e)
    return {"generated_by": "scripts/knowledge_registry.py", "statuses": STATUSES, "rights_hints": HINTS, "sections": SECTIONS, "entries": entries}


def report(reg: dict) -> str:
    es = reg["entries"]
    by = lambda key: {k: sum(1 for e in es if e[key] == k) for k in sorted({e[key] for e in es})}  # noqa: E731
    out = ["# VIDHI â€” knowledge registry (Phase 2)", "",
           "Generated from `scripts/knowledge_registry.py`; the machine-readable copy is `backend/data/knowledge/registry.json`. **This is a catalogue, not content: no text of any work has been located, downloaded or indexed.**", "",
           "## Dashboard (actual status, from the registry file)", "", "| Measure | Count |", "|---|---|",
           f"| Numbered entries on the owner's list | {len(es)} |", f"| Distinct works (after resolving repeats) | {sum(1 for e in es if e['canonical_of'] is None)} |"]
    for s in STATUSES:
        out.append(f"| Status: {s} | {sum(1 for e in es if e['status'] == s)} |")
    out += [f"| Source located | {sum(1 for e in es if e['source_status'] != 'not_located')} |", f"| Rights verified | {sum(1 for e in es if e['rights_status'] != 'not_verified')} |", "",
            "## Rights first impressions (UNVERIFIED hints, not statuses)", "", "| Hint | Entries | Meaning |", "|---|---|---|"]
    for h, c in by("rights_hint").items():
        out.append(f"| `{h}` | {c} | {HINTS[h]} |")
    out += ["", "## Duplicate-resolution report", "",
            "| Entry | Is the same work as | Treatment |", "|---|---|---|"]
    for dup, canon in CANONICAL.items():
        d = next(e for e in es if e["number"] == dup)
        c = next(e for e in es if e["number"] == canon)
        out.append(f"| #{dup} {d['title']} | #{canon} {c['title']} | One source record (#{canon}); #{dup} stays discoverable inside its collection and points to it. Never indexed twice. |")
    out += ["", "**Not a duplicate (same title, different work):** #10 *The Art of War* (Sun Tzu) and #28 *The Art of War* (Machiavelli). They keep separate records and must never be merged by title.", "",
            "## Collections", ""]
    for c, nums in COLLECTIONS.items():
        out.append(f"* **{c.replace('_', ' ')}**: " + ", ".join(f"#{n}" for n in nums))
    out += ["", "## Entries", "", "| # | Title | Author(s) | Sec. | Kind | Status | Rights hint | Phases |", "|---|---|---|---|---|---|---|---|"]
    for e in es:
        dup = f" (= #{e['canonical_of']})" if e["canonical_of"] else ""
        out.append(f"| {e['number']} | {e['title']}{dup} | {e['authors']} | {e['section']} | {e['kind']} | {e['status']} | `{e['rights_hint']}` | {', '.join(map(str, e['planned_for_phases'])) or '-'} |")
    out += ["", "Edition, translator and year are empty on purpose: they will be recorded from a real copy or catalogue entry, never from memory. Authors and titles are as the owner listed them and have not been checked against a catalogue.", ""]
    return "\n".join(out)


if __name__ == "__main__":
    reg = build()
    (DATA / "registry.json").write_text(json.dumps(reg, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    (DOCS / "VIDHI_KNOWLEDGE_REGISTRY.md").write_text(report(reg), encoding="utf-8")
    print(f"{len(reg['entries'])} entries written")

