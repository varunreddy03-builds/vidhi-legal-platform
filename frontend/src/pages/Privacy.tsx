import { Link } from "react-router-dom";
import { LegalShell, Ph, Section, useLegalConfig } from "@/lib/legal";

/**
 * Privacy policy DRAFT. It describes what the software actually does (kept in step with docs/DATA_STORAGE.md). Whether it satisfies the operator's legal
 * duties, for example under India's Digital Personal Data Protection Act, 2023, is for a qualified lawyer to decide: see LEGAL_REVIEWED in lib/legal.tsx.
 */
export default function Privacy() {
  const { data } = useLegalConfig();
  const c = data?.config ?? {};
  return (
    <LegalShell title="How VIDHI handles your data" doc="privacy" testId="privacy-page">
      <Section title="Who is responsible">
        <p>
          VIDHI is run by <Ph value={c.legal_name} label="Legal entity name" />, <Ph value={c.registered_address} label="Registered address" />.
        </p>
        <p>
          Grievance officer / privacy contact: <Ph value={c.grievance_name} label="Grievance officer's name" />,{" "}
          <Ph value={c.privacy_email} label="Privacy contact email" />.
        </p>
      </Section>
      <Section title="What VIDHI stores">
        <p>Your account: name, email address, a hashed password (never the password itself), your role and your organisation&apos;s name. If you sign in with Google, Google&apos;s account identifier and your verified email address. No Google access tokens are kept.</p>
        <p>What you put into the product: matters, uploaded documents and their extracted or scanned text, facts, timeline entries, research questions and answers, drafts, recovery cases, proof files, payment records you enter, and the names and email addresses of people you add (for example a debtor or an accountant).</p>
        <p>Your choices and safety information: language and theme, two-step sign-in settings (the secret is encrypted), and, if you add one, your phone number for alerts (encrypted; only the last four digits are readable). Thumbs up or down you give to answers, and the requests you make about your data.</p>
        <p>A record of activity (who did what, and when) for your organisation, and a log of emails sent through VIDHI with their delivery status.</p>
        <p>Voice: a recording you make to speak a question, and text read aloud to you, are processed to give you the result and are not stored. Only a usage counter is kept.</p>
      </Section>
      <Section title="Who can see it">
        <p>Only people in your organisation, according to their role. Other organisations cannot see your data. The people who operate the VIDHI service can technically reach the database in order to run it. Uploaded files are encrypted at rest and backups are encrypted.</p>
      </Section>
      <Section title="Services that process data for us">
        <p><strong>AI.</strong> When you run research, read a scanned document, draft or translate a notice, or ask a question, the relevant text, and for scans the page images, are sent to an AI service to produce the answer: Google Gemini, Anthropic Claude (which may be reached through OpenRouter), or Groq. The system may switch between them. Do not use those features for material you are not allowed to share with such a service. Text inside your documents is treated as information to read, never as instructions, and a person should always check AI output.</p>
        <p><strong>Voice.</strong> Spoken questions and text to be read aloud may be processed by ElevenLabs or Google Gemini.</p>
        <p><strong>Messages.</strong> Email is delivered by Resend or SendGrid. If you switch on phone alerts, text messages go through Twilio. Alerts contain no names or amounts and are only ever sent to your own verified number, never to the other side of a matter.</p>
        <p><strong>Payments.</strong> Upgrades are paid on the secure pages of Stripe, Razorpay or PayPal. Your card, UPI or PayPal details go to them; VIDHI never sees or stores them.</p>
        <p><strong>Sign-in.</strong> If you choose it, Google sign-in.</p>
        <p><strong>Error reports.</strong> If error tracking is switched on, technical error reports, with document text and personal details removed, go to Sentry so problems can be fixed.</p>
        <p>Each of these providers has its own terms and privacy policy.</p>
      </Section>
      <Section title="Processing outside India">
        <p>
          The AI, voice, messaging and payment providers above process data on their own systems, and several of them do so outside India. Where our own servers are located is
          configured by the operator and does not change this. By using those features you understand that the relevant text, audio or images are sent to them. The operator
          will confirm and record each provider&apos;s location and terms before launch; until then, please do not describe VIDHI as keeping all data in India.
        </p>
      </Section>
      <Section title="Cookies and similar storage">
        <p>
          One cookie keeps you signed in, and a short-lived one is used while you sign in with Google. Your browser also stores your language, theme and a few settings. There are no advertising or tracking
          cookies. Details: <Link to="/cookies" className="underline underline-offset-4">Cookie policy</Link>.
        </p>
      </Section>
      <Section title="How long we keep it, and deleting it">
        <p>Your data is kept until you delete it. Nothing is deleted automatically unless an owner or admin turns on a retention period; if they do, owners are emailed 30 days before anything closed is deleted, and a matter under legal hold is never deleted.</p>
        <p>Deleting a matter or a recovery case removes its documents, records and email records. The activity log keeps a line saying it happened, with the descriptive text removed.</p>
        <p>An owner can erase the whole organisation at any time. Copies inside encrypted backups disappear when those backups expire (30 days).</p>
        <p>Addresses that bounced or complained are remembered so we never email them again; this is the only thing kept about an address after erasure. Payment records are kept for accounting but no longer point to any person.</p>
      </Section>
      <Section title="Your rights and how to use them">
        <p>
          You can ask to see the personal data we hold about you, to correct it, to have it erased, to withdraw a consent, to nominate someone to act for you, or to complain. These are
          described to you as a summary of the kinds of rights found in India&apos;s Digital Personal Data Protection Act, 2023; a lawyer will confirm exactly which apply.
        </p>
        <p>
          Use <Link to="/data-rights" className="underline underline-offset-4">Your data rights</Link>: you can download your own data at once and send a request, and we acknowledge it by email. Our target is to reply
          within <strong>{data?.response_days ?? 30} days</strong>; that is a service target, not a statement of any legal deadline. You can also write to the grievance officer named above.
        </p>
        <p>Owners and admins can also download everything in the organisation (Settings). Anyone can change their password or sign out of every device.</p>
      </Section>
      <Section title="Children">
        <p>VIDHI is for adults. It is not meant for anyone under 18, and the operator&apos;s counsel will confirm the exact wording and any consent rules that apply.</p>
      </Section>
      <Section title="What VIDHI is not">
        <p>VIDHI is a research and organisation tool. It does not give legal advice, and its AI output must be checked by a lawyer before anyone relies on it.</p>
      </Section>
      <Section title="Changes">
        <p>If this policy changes in a way that matters, we will tell signed-in users before it takes effect.</p>
      </Section>
    </LegalShell>
  );
}