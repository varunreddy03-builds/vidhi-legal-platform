/**
 * EVERY legal or government fact the Legal Recovery guide shows lives in this one file, not in the screens.
 *
 * Nothing here has been confirmed against an official source. Each fact is marked "TODO: verify", and the screens show that mark next to the sentence it belongs to, until a
 * person compares the line with the official portal or Act, changes its status to "verified" AND sets LAST_VERIFIED to that day (an ISO date, YYYY-MM-DD). The tests refuse a
 * "verified" fact while LAST_VERIFIED is empty, and refuse a fact sentence that lives anywhere else in the front end.
 *
 * Wording that is not a fact (the questions, the buttons, "keep these ready") stays in guideStrings.ts. A sentence there that sounds like a legal or government fact must be listed in
 * FACT_STRING_KEYS below; tests/guide rules check this, so a new such sentence cannot slip in unmarked.
 */
export type FactStatus = "TODO: verify" | "verified";
export interface Fact {
  /** The sentence as a person would read it. */
  text: string;
  status: FactStatus;
  /** Where the guide uses it, so whoever verifies knows what depends on it. */
  usedFor: string;
}

// TODO: verify - the day a person last compared every line below with the official source. Empty until then, and the screen says so.
export const LAST_VERIFIED: string = "";

const todo: FactStatus = "TODO: verify";

export const FACTS = {
  portalExists: {
    text: "The government runs a free online dispute resolution (ODR) portal for delayed payments owed to micro and small enterprises.",
    status: todo,
    usedFor: "the portal card title and button",
  },
  portalUrl: {
    text: "https://odr.msme.gov.in",
    status: todo,
    usedFor: "the address the 'Open the official portal' button opens (a new tab)",
  },
  effectiveDate: {
    text: "15 October 2025",
    status: todo,
    usedFor: "the date shown as when the portal applies from (from the owner's brief of 2026-10-30; the cases it covers are not stated)",
  },
  whoMustUse: {
    text: "A registered micro or small enterprise (Udyam registration) that is owed money by a business buyer for goods or services.",
    status: todo,
    usedFor: "who the portal is for, and the order of the two routes (the guide only suggests the portal first; it does not say it applies to a person's case)",
  },
  whatItCovers: {
    text: "It is free and covers conciliation, mediation and arbitration.",
    status: todo,
    usedFor: "what the portal card says the portal does",
  },
  udyamMeaning: {
    text: "Udyam registration is a free online registration for micro, small and medium businesses.",
    status: todo,
    usedFor: "the 'not sure' explanation",
  },
  notRegisteredSkip: {
    text: "The free portal is not the first step for a business that is not registered as a micro or small enterprise.",
    status: todo,
    usedFor: "why the portal is skipped when the seller says it is not registered",
  },
  individualBuyerSkip: {
    text: "The free portal is for business buyers, so it is not the first step when the buyer is an individual consumer.",
    status: todo,
    usedFor: "why the portal is skipped when the buyer is an individual",
  },
  portalChecklist: {
    text: "The papers in the checklist are what the portal is expected to ask for.",
    status: todo,
    usedFor: "the 'keep these ready' list on the portal card",
  },
  emailService: {
    text: "Email delivery may not be accepted as formal service in every situation.",
    status: todo,
    usedFor: "the caution next to the 'send by email' option",
  },
  courtOrArbitration: {
    text: "A lawyer can advise on recovery through court or arbitration.",
    status: todo,
    usedFor: "the escalation step",
  },
  overdueCutoffs: {
    text: "The overdue choices 'under 15', '15 to 45' and 'over 45' days come from the owner's brief.",
    status: todo,
    usedFor: "the labels of question 4 only: the answer is saved and used for nothing else, and no rule is claimed",
  },
} as const satisfies Record<string, Fact>;

export type FactId = keyof typeof FACTS;

/** Portal details with no sentence of fact in them. The paper list is a plain checklist, marked through the `portalChecklist` fact. */
export const PORTAL_RULES = {
  lastVerified: LAST_VERIFIED,
  portalUrl: FACTS.portalUrl.text,
  name: "MSME online dispute resolution (ODR) portal",
  // TODO: verify - eligibility notes the portal itself states (for example an overdue period or an amount limit). Add them here, as facts with a status, when checked.
  eligibilityNotes: [] as string[],
  checklist: [
    "Your Udyam registration number and certificate",
    "The invoice, bill or purchase order",
    "Delivery proof: challan, lorry receipt, delivery message or signed copy",
    "Messages, emails or letters about payment, including any promise to pay",
    "Your bank statement showing what was and was not received",
    "The buyer's full name, address, phone and email",
  ],
};

/** The mark beside every point of law in the help panel below: VIDHI names the point and states nothing about it. */
export const ADVOCATE_TO_CONFIRM = "advocate to confirm";

/** "How to write a payment notice" (the help panel above the notice, components/recovery/NoticeHelp.tsx). Drafting help from the owner's brief of 2026-11-10, not law:
 * the points of law are only named, each with the "advocate to confirm" mark, and nothing here says what the law is. */
export const NOTICE_HELP: { title: string; sections: { heading: string; ordered?: boolean; points: string[] }[]; lawHeading: string; lawIntro: string; lawPoints: string[] } = {
  title: "How to write a payment notice",
  sections: [
    {
      heading: "What it is",
      points: ["A formal letter saying the money is overdue and asking for payment by a fixed date.", "It is not a court order."],
    },
    {
      heading: "Order of the letter",
      ordered: true,
      points: [
        "Title",
        "Date and place",
        "From: your name, address, Udyam number and GSTIN",
        "To: the buyer's exact name and address",
        "One-line subject with the amount",
        "Numbered paragraphs in date order: who you are; the order or contract; delivery; a table of the invoices; payments received and the balance; earlier reminders; the legal basis; the demand to pay within 15 days; what you will do otherwise",
        "Signature",
        "List of enclosures",
      ],
    },
    {
      heading: "Sending",
      points: ["Send it by Registered Post with acknowledgement due or by Speed Post, and also by email.", "Keep the receipts."],
    },
    {
      heading: "Style",
      points: ["Exact dates and amounts.", "Facts only.", "No threats or insults.", "Simple sentences."],
    },
  ],
  lawHeading: "Points of law",
  lawIntro: "VIDHI does not say what the law is on these points. Ask an advocate about each one before you rely on it.",
  lawPoints: [
    "Which sections of the MSMED Act, 2006 apply to your claim",
    "The rule for interest on a delayed payment",
    "The date of your Udyam registration, and what depends on it",
    "Whether a notice is needed before going to the Council",
  ],
};

/** A guide sentence that carries a legal or government fact, and the facts behind it. The screen puts the "TODO: verify" mark next to it while any of them is unverified. */
export const FACT_STRING_KEYS: Record<string, FactId[]> = {
  portalTitle: ["portalExists"],
  skipNotRegistered: ["notRegisteredSkip"],
  skipIndividual: ["individualBuyerSkip"],
  unsureBody: ["udyamMeaning"],
  emailNote: ["emailService"],
  escalateBody: ["courtOrArbitration"],
};

/** A fact counts as verified only when it says so AND a verification day is recorded (the optional arguments exist so tests can try other states). */
export function isVerified(fact: Fact, lastVerified: string = LAST_VERIFIED): boolean {
  return fact.status === "verified" && lastVerified !== "";
}

/** True while any of these facts is not verified: the screen then shows the mark. */
export function needsVerifying(ids: readonly FactId[], facts: Record<string, Fact> = FACTS, lastVerified: string = LAST_VERIFIED): boolean {
  return ids.some((id) => !isVerified(facts[id], lastVerified));
}

export type PortalRoute = "portal_first" | "skip_not_registered" | "skip_individual" | "unsure";

/** The routing from the owner's brief. It decides only which card is shown first. */
export function routeFor(udyam: "yes" | "no" | "not_sure", buyer: "business" | "individual"): PortalRoute {
  if (udyam === "not_sure") return "unsure";
  if (udyam === "yes" && buyer === "business") return "portal_first";
  if (buyer === "individual") return "skip_individual";
  return "skip_not_registered";
}
