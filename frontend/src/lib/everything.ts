// Everything VIDHI does, in one list, so the Start page and the About page cannot disagree. Plain English; each line says what it is for and, where it matters, what it cannot do yet.
// Keep this honest: if a part needs set-up or is not built, say so here.

export type Part = { id: string; to: string; name: string; what: string; limit?: string };
export type Group = { id: string; title: string; intro: string; parts: Part[] };

export const GROUPS: Group[] = [
  {
    id: "intelligence",
    title: "Legal Intelligence",
    intro: "Research, cases, drafting and documents, with sources shown for every answer.",
    parts: [
      { id: "research", to: "/research", name: "Ask and Research", what: "Ask a legal question and get an answer with the sources it relies on. Each claim is marked Verified, Partly verified or Unsupported by the program's own checks, never by the AI's opinion.", limit: "A claim is Verified only when exact text from the reviewed law library supports it. Until advocates have reviewed more of the library, most answers will say so." },
      { id: "matters", to: "/matters", name: "Matters", what: "A case file: documents, facts, a timeline, people, evidence, a graph of how they connect, and notes. Upload a document and VIDHI reads it, summarises it and flags contract clauses with quotes it has checked." },
      { id: "drafts", to: "/drafts", name: "Drafts and templates", what: "Write and keep drafts, start from templates, send one to a colleague for approval, and check a draft's citations." },
      { id: "vault", to: "/vault", name: "Vault", what: "A workspace for many documents at once: add them in bulk, get a summary of each, and fill one review table that asks the same questions of every document, with an exact quote and page for every answer.", limit: "Each answer is marked Quote found, Unconfirmed or Nothing reported. Check the document before relying on any cell." },
      { id: "tax", to: "/tax", name: "Tax", what: "A place for tax matters and notices, with a notice-reply outline built from what you type.", limit: "VIDHI carries no tax law of its own: every legal point in the outline is left blank for you to fill from a source you have checked." },
      { id: "translate", to: "/translate", name: "Translate and transcribe", what: "Translate between English and the supported Indian languages, or turn a recording into text first. The program checks that every number survived.", limit: "It cannot judge the quality of the language: have someone fluent read it before it is used." },
      { id: "law", to: "/law", name: "Law library", what: "Acts and Rules cut into sections for looking things up, with where each came from.", limit: "Loaded text is a draft until an advocate has compared it with the official text. Some publishers' Acts stay hidden until their terms of use have been checked." },
      { id: "judgments", to: "/judgments", name: "High Court judgments", what: "Look up judgments of the Supreme Court and the High Courts, with the court, date and a link to the source.", limit: "A judgment is a record to read. VIDHI never says a judgment is still good law." },
      { id: "directory", to: "/legal-directory", name: "Courts and legal directory", what: "Where things are: courts and tribunals, official portals, High Court websites, legal aid bodies and Law Commission of India reports. A link is shown only after it has been checked.", limit: "It points to sources; it does not copy their text, and a Law Commission report is a recommendation, not law." },
    ],
  },
  {
    id: "katalyst",
    title: "Legal Katalyst",
    intro: "Five checks a lawyer runs on their own work before it goes out. Each says where its answer came from and what it could not check.",
    parts: [
      { id: "authority", to: "/katalyst/authority", name: "Authority Check", what: "Upload a draft: VIDHI finds every case and section it cites and checks each against a source. Whether a case is still good law is not checked." },
      { id: "deadlines", to: "/katalyst/deadlines", name: "Deadline engine", what: "Works out a date only from a rule that a person entered from an official source and a named reviewer marked as reviewed, and shows every step." },
      { id: "oldcode", to: "/katalyst/oldcode", name: "Old-code to new-code checker", what: "Lists every place a draft names the IPC, the CrPC or the Evidence Act, and shows a newer section only where a reviewed mapping exists." },
      { id: "defects", to: "/katalyst/defects", name: "Pre-filing defect check", what: "Checks a draft against a checklist before filing and lists what looks missing." },
      { id: "dates", to: "/katalyst/dates", name: "List of dates", what: "Builds a list of dates from a document, each with its page reference." },
    ],
  },
  {
    id: "together",
    title: "Working with others",
    intro: "Colleagues, clients and the tools you already use.",
    parts: [
      { id: "reviews", to: "/matters", name: "Reviews", what: "Inside a matter, ask a colleague to review a research answer, a draft, a document or its analysis. They approve or ask for changes, and it is recorded." },
      { id: "portal", to: "/portal", name: "Client portal and shared graph", what: "Share chosen documents and updates with a client, read-only. A lawyer can also publish a filtered graph of how the shared documents connect; it never includes the firm's own claims, contradictions or evidence." },
      { id: "conflicts", to: "/conflicts", name: "Conflict checks", what: "Check a name against your matters before taking a new one." },
      { id: "connections", to: "/connections", name: "Connections", what: "Word: review a draft inside Word. Microsoft 365: copy a file or an email from your own account into a matter, read-only.", limit: "Microsoft 365 needs the operator to register VIDHI first, and has not yet been run against a real tenant. iManage is not built." },
    ],
  },
  {
    id: "trust",
    title: "How VIDHI keeps its word",
    intro: "The rules the program enforces itself.",
    parts: [
      { id: "rules", to: "/security", name: "Security and compliance", what: "What the software does to protect your data: encryption, roles, firm separation, two-step sign-in and an activity log. It does not claim SOC 2 or ISO 27001 certification, which need an outside audit.", limit: "Terms, Privacy and this page are drafts until a qualified lawyer has reviewed them." },
      { id: "signoff", to: "/law", name: "Advocate review", what: "Advocates compare the library's text with the official text. They are shown only by a code such as Advocate R-01, never by name. A confirmation never makes anything verified by itself, and a judgment can never be marked verified." },
      { id: "neutral", to: "/help", name: "Neutral wording", what: "VIDHI flags differences between sources and never says a person lied. Documents you upload are treated as data to read, never as instructions." },
    ],
  },
];

export const PROMISE = "VIDHI assists; it does not give legal advice. AI assists. Sources support. Graphs connect. Logic verifies. Lawyers decide.";
