# Technical decisions (and why)

Written from the code as it is, not from a wish list. Where something is a recommendation rather than built, it says so.

## 1. Intelligence comes from the pipeline, not from a bigger model
No foundation model is trained: there is no demonstrated need and no budget that justifies it. Answer quality comes from four layers, each testable:
1. **Models, swappable.** `lib/ai.py` routes every task through a chain of providers (Gemini, Claude Sonnet/Haiku directly or via OpenRouter, Groq), by task and plan, with automatic fall-through. Models and providers are environment settings, so changing provider needs no rebuild. The free plan can only reach light models.
2. **Retrieval.** (a) Matter documents: every document is always listed; if all text does not fit, each document still gets its best passage and the answer states exactly what was not read (`lib/matter_context.py`, BM25-style scoring). Tokenization is now **Unicode-aware**: before this review it only understood a-z, so Hindi, Tamil, Telugu and other Indian-language documents were invisible to search. (b) Law: only the verified library can verify a citation. A question in another language is first turned into an English search query (a light model, question text only) because the library is English; the model still answers the original question in the person's language.
3. **Reading documents.** Text PDFs, Word and text files are extracted in code. **Scanned PDFs and photos are read by a vision model** (Gemini, or Claude directly) page by page, in the language written, and marked "read from a scan by AI" because a model can misread. Quality on handwriting and some regional scripts will vary: measure it before promising it.
4. **Verification by code, never by the model.** The model proposes; `lib/verify.py` checks every quote against the stored text and every legal claim against the verified library. A hijacked or mistaken model therefore cannot make an unsupported claim look verified (tested in `tests/test_prompt_injection.py` and the 35-case set in `evals/`).

## 2. What was deliberately NOT built, and why
- **Embedding / vector search.** The right next step once the verified library has real content (roughly 50+ provisions): add an embedding index (for example Gemini embeddings) next to the keyword search, and measure it on `evals/`. Not built now because the library is empty, so there is nothing to measure it against, and an untested retrieval layer would add risk without evidence of benefit.
- **Court case-status lookup, e-signature, e-stamping.** Deferred as instructed. `lib/esign.py` (when added) is only an extension point for an authorised provider such as Digio or Leegality.
- **A new database or search service.** MongoDB with GridFS already covers the needs; adding a service would add cost and failure modes.

## 3. How quality is measured
`backend/evals/legal_qa.json` holds 35 cases (grounded answers, invented quotes, law not in the library, fictional library law, absence claims, neutral wording, injection, answering in Hindi/Telugu/Tamil, saying what is missing). `evals/scoring.py` scores an answer by code. CI runs the cases with scripted replies to prove the pipeline's guarantees. `python scripts/eval_answers.py --base-url ...` runs them against a **real model** on a test server and prints a score: do this before every change of model or prompt. Answer thumbs up/down is stored per answer to find real-world weak spots.

## 4. Privacy, security and where data goes
- Uploaded files are encrypted at rest; secrets sealed; sessions hashed; every query is scoped by organisation.
- **AI processing leaves India.** When a person runs research, scan reading or a notice draft, the relevant text is sent to the AI provider chosen for that task (Google, Anthropic, Groq, OpenRouter). That is cross-border processing and must be disclosed in the privacy policy and covered by each provider's data-processing terms (see below). Choosing an Indian cloud region for our own servers does **not** change this.
- Untrusted text is fenced as data and instruction-like text is flagged (`lib/safety.py`).

## 5. Where each outside service processes data (to confirm, NOT yet verified)
This table is a checklist from general public knowledge, not a verified statement. Before launch, read each provider's current data-processing terms and record the real answer.

| Service | Receives | Believed location | To confirm |
|---|---|---|---|
| Google Gemini API | question and document text, scans | outside India (global) | retention and training terms for the API tier used |
| Anthropic / OpenRouter | same, for Claude tasks | outside India (US) | zero-retention option, OpenRouter's routing |
| Groq | free-plan light tasks | outside India (US) | retention terms |
| ElevenLabs | spoken audio, text to read aloud | outside India | retention of audio and text |
| Twilio / SendGrid | phone number and alert text / email content | outside India (US) | regions available, India SMS registration (DLT) |
| Stripe / PayPal | payment details (never reach VIDHI) | outside India | their own compliance |
| Razorpay | payment details (never reach VIDHI) | India | their own compliance |
| Our servers and MongoDB | everything stored | the region YOU choose when deploying (Mumbai recommended) | backups, logs and monitoring (Sentry) also leave the region unless configured otherwise |

Nothing in the product may claim "your data stays in India" until each row has been checked and the architecture changed where it does not hold.