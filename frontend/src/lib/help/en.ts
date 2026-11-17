import type { HelpContent } from "./types";

const en: HelpContent = {
  name: "English",
  note: "",
  ui: {
    tour: "Take a quick tour",
    sample: "Try a sample case",
    helpCentre: "Help centre",
    next: "Next",
    back: "Back",
    skip: "Skip",
    done: "Done",
    step: "Step {n} of {total}",
    search: "Search the help",
    noResults: "Nothing matches that.",
    language: "Language",
    contact: "Contact support",
    sampleMade: "A sample case was added. Every name and amount in it is invented.",
  },
  tour: [
    { title: "Welcome to VIDHI", text: "VIDHI helps you organise matters and prepare documents. It does not give legal advice." },
    { title: "Ask a question", text: "Use Ask a question for quick answers with sources. Check anything important yourself." },
    { title: "Matters", text: "Keep each case in a matter: upload documents and see the facts, the timeline and the people." },
    { title: "Dates", text: "Save hearings and deadlines on Dates, and we will remind you." },
    { title: "Help", text: "Open Help and support any time. Try a sample case to practise." },
  ],
  sections: [
    {
      title: "Getting started",
      items: [
        { q: "What is VIDHI?", a: "VIDHI is a research and self-help tool. Its Legal Katalyst has five tools for lawyers (Authority Check, Deadline engine, Old-code to new-code checker, Pre-filing defect check, List of dates with page references; only Authority Check is built so far), with matters, documents, source-checked research and drafting around it. Legal Recovery, under More, is for anyone owed money (organise proof, understand the case, prepare a demand notice). It is not a law firm and does not give legal advice. This help is general information, not legal advice." },
        { q: "Is the AI's answer reliable?", a: "AI helps read and draft. A statement is shown as verified only when its exact words are found in a source that was checked. The law library may be empty until lawyers add to it. Check anything that matters with a lawyer." },
        { q: "How do I try it without my own data?", a: "Press Try a sample case on the home page. It makes a fictional matter that you can open, search and delete." },
      ],
    },
    {
      title: "Legal Recovery",
      items: [
        { q: "How do I prepare a demand notice?", a: "Open Legal Recovery, add a case, upload proof, press Understand my case, fill in the details and create the notice. Read it carefully, approve it, then send or download it. Nothing is sent without your approval." },
        { q: "Does VIDHI say whether I will win?", a: "No. It organises your papers and points out gaps. It does not predict results or say which law applies; a lawyer must decide that." },
      ],
    },
    {
      title: "Matters and research",
      items: [
        { q: "What are matters and documents?", a: "A matter is a case file. Upload PDFs, Word files, images, audio or video. Scanned pages are read by AI and flagged so that you can check them." },
        { q: "What do verified and unsupported mean?", a: "Verified: the exact words were found in a source on file. Partly verified: some support was found. Unsupported: nothing was found. These labels are decided by code, not by the AI." },
        { q: "How do dates and hearings work?", a: "Save a date on the Dates page. If you choose, VIDHI reminds you by email, notification or text message. It does not look up courts: the dates are yours, so check them yourself." },
      ],
    },
    {
      title: "Account and privacy",
      items: [
        { q: "How do I keep my account safe?", a: "Use a strong password and turn on two-step sign-in in Settings (required for owners and admins of teams). Look at Signed-in devices from time to time." },
        { q: "What happens to my data?", a: "Your documents are stored encrypted and belong to your organisation. You can export or delete them; see Privacy and Your data rights. The privacy text is a draft until a lawyer has reviewed it." },
        { q: "How do I contact support?", a: "Use Help and support; we reply by email. Do not send passwords or card numbers." },
      ],
    },
  ],
  extra: [
    {
      title: "Checking a draft",
      items: [
        { q: "How do I check the cases and sections my draft cites?", a: "Open Legal Katalyst, then Authority Check, and paste the draft or choose a file. VIDHI lists every case and section it finds and says, for each, what could and could not be checked. On the result, press What do these labels mean? \"Could not check\" and \"Not in reviewed library\" are not findings that a reference is wrong, and whether a case is still good law is not checked. You can mark each reference to fix, accept or reviewed, and download a Word or PDF copy. A saved report is deleted automatically on the date shown on it." },
        { q: "I have no draft to try it on.", a: "On the home page press New here? Try Authority Check on a made-up sample draft. The sample is fictional and nothing is sent until you press Check this draft." },
        { q: "What does Check this draft do?", a: "Open a draft in Drafts and press Check this draft. It lists items still open in [square brackets], names, dates and amounts that no longer match the answers you gave a template, dates that do not exist and years that look like a typing slip. Each item takes you to the place in the text. It only points things out: it changes nothing, and it is not a check of the law or of your facts." },
        { q: "What are templates?", a: "Templates (a rent agreement, a loan agreement, an NDA, a legal notice for a returned cheque and an employment letter) make a draft from your answers. The words are filled in by program code, not by AI. No lawyer has reviewed a template unless the draft says so, and anything about the law is left as a [LAWYER TO CONFIRM] item for a lawyer." },
      ],
    },
    {
      title: "Files and a poor connection",
      items: [
        { q: "Can VIDHI read a scanned document?", a: "Yes. Scanned pages are read by a machine and marked as uncertain. Check the wording against the page before you rely on it." },
        { q: "My connection dropped while I was uploading.", a: "The upload says that your file was not sent and sends it again by itself when the connection comes back, so you do not need to choose the file again. If it keeps failing, try again on a better connection." },
        { q: "Does my draft save by itself?", a: "Yes. While you type, a copy is kept on your device and the draft is saved a few seconds later. The line under the draft says whether it is saved, saving, kept on this device only, or not saved. If a copy kept on your device is newer than the saved draft, you are asked whether to bring it back." },
      ],
    },
    {
      title: "Your team and your plan",
      items: [
        { q: "Who can do what?", a: "An owner or admin manages the team and can delete. A lawyer can use the AI features and email other people. A member can read and write records but cannot use the AI features, email other people or delete. A client invited from a matter sees only that matter." },
        { q: "How does a senior review a junior's draft?", a: "On the draft, the author presses Send for review. A lawyer, admin or owner who did not write it then sees Approve and Ask for changes (with a one-line reason). The status line says who decided and when. Any change to the text afterwards returns the draft to Draft, so Approved always means this exact text. Approval is a record: it does not stop anyone from exporting or sending. In an organisation with one person, that person can approve their own draft. Everyone can write comments on a draft; a comment cannot be edited or deleted, only marked resolved, and comments are never sent to the AI." },
        { q: "What do Free and Pro include?", a: "Settings shows the comparison and how many AI requests you have used today. The free plan has a small number of AI requests a day, and two tasks are for Pro only: reading every document in a matter together, and clause-by-clause contract review. A Firm plan for a whole firm also exists: it has more AI requests a day, shared by the organisation, and a limit on the number of people. VIDHI sets it up by hand; there is no online checkout for it yet." },
        { q: "Where are the theme and language settings?", a: "Open the account menu at the top right. You can choose a light or dark look and your language there, and reach Settings and Sign out." },
      ],
    },
    {
      title: "Law and judgments",
      items: [
        { q: "Why does the law library say not reviewed?", a: "Texts loaded from official sources are shown as unverified until a named lawyer has compared them with the official text. Nothing in the library or in the High Court judgments is a statement that a case is still good law." },
        { q: "Why does a judgment have no text?", a: "Many judgments are listed with their details only. When you open one, VIDHI tries to fetch its text from the public court archive. If that cannot be done, open the court's PDF with the link on the judgment." },
      ],
    },
    {
      title: "Legal Katalyst tools",
      items: [
        { q: "What does the Deadline engine do?", a: "It works out a due date from a rule that a person entered and a named reviewer marked as reviewed. VIDHI contains no law of its own, so until reviewed rules are loaded it has none to use, and it may be switched off on your server. It shows every step of the working so that you can check it by hand. A calculation is not stored; a line is written to the activity log." },
        { q: "What does the Old-code to new-code checker do?", a: "It reads a draft page by page and finds where the Indian Penal Code, the Code of Criminal Procedure or the Indian Evidence Act is named, with the section numbers written next to the name. It does not know what a section says. A section is matched to the new code only from a mapping that a lawyer has reviewed; where there is none, it says so." },
        { q: "What does the Pre-filing defect check do?", a: "It reads a draft page by page and points to places to look at: blanks and placeholders left unfilled, paragraph numbers that skip or repeat, an annexure series with a label missing, a reference to a paragraph that is not there, and a word typed twice. It knows no court's rules, so it cannot say that a filing will be accepted or rejected, and it changes nothing. Each finding says why it may not be a slip." },
        { q: "What does the List of dates with page references do?", a: "It finds the dates written in a document and lists them with the page each one is on. It never decides what a date means and never says a date is wrong. It marks a date it could not read cleanly: not a real calendar date, a day and month that could swap, a year with two digits, or no day given. Numbers like 12/03/2021 are read as day, month, year." },
      ],
    },
  ],
};

export default en;