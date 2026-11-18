import { Link } from "react-router-dom";
import { LegalShell, Section } from "@/lib/legal";

/**
 * Security and compliance, in plain words. Every line describes something the code does today (see docs/ARCHITECTURE_NOTES.md, docs/DEPLOYMENT.md, docs/SECURITY_AUDIT.md).
 * It must never claim a certification or an audit that has not happened: SOC 2 Type II and ISO/IEC 27001 are given by outside auditors, and VIDHI has neither.
 */
export default function Security() {
  return (
    <LegalShell title="Security and compliance" doc="security" testId="security-page">
      <Section title="Where VIDHI stands">
        <p data-testid="security-standards">
          VIDHI has <strong>not</strong> been audited for SOC 2 Type II or certified to ISO/IEC 27001. Those are given by independent auditors after a review period, and we will not say we have them until we do. What follows is what the
          software itself does today, so your own advisers can judge it.
        </p>
      </Section>
      <Section title="Encryption">
        <p>Uploaded files are encrypted before they are stored (AES-256-GCM). The text read out of your documents is encrypted in the database with the same key, so a copy of the database alone does not show your documents.</p>
        <p>Database backups are encrypted (AES-256) and checked that they can be opened. Connections to the live site use HTTPS, and the site tells browsers to insist on it.</p>
        <p>Passwords are stored only as salted hashes (bcrypt). The secret behind two-step sign-in is stored encrypted.</p>
      </Section>
      <Section title="Who can see what">
        <p>Each firm&apos;s data is kept apart: every request is tied to the signed-in person&apos;s organisation, and tests try, and must fail, to read another firm&apos;s matters.</p>
        <p>Roles decide what a person may do (owner, admin, lawyer, member). A client sees only what a lawyer has chosen to share with them. Anything not allowed by the role table is refused by default.</p>
        <p>You can turn on two-step sign-in with an authenticator app, and sign in with Google where the operator has switched that on. Sign-in attempts are rate-limited.</p>
        <p>Actions that matter (signing in, deleting, sharing, exporting) are recorded in an activity log that owners and admins can read.</p>
      </Section>
      <Section title="AI and your documents">
        <p>Document text goes to an AI provider only when a person uses an AI feature on it. VIDHI does not train any model on your documents. Text inside an uploaded document is treated as data to read, never as instructions to the AI.</p>
        <p>The AI never decides whether a legal point is verified: the program checks quotes and sources itself, and says plainly when it could not.</p>
      </Section>
      <Section title="Your data">
        <p>An owner can export the firm&apos;s data and can erase the whole organisation, which removes its matters, documents, facts, tables and drafts. Files are removed when their matter or document is deleted, and old records are cleared on a schedule. See <Link to="/data-rights" className="underline underline-offset-4">your data rights</Link> and the <Link to="/privacy" className="underline underline-offset-4">privacy notice</Link>.</p>
      </Section>
      <Section title="GDPR, CCPA and India's DPDP Act">
        <p>
          The product has the tools these laws ask a service to provide: a privacy notice, access and export, correction and erasure on request, a limit on how long records are kept, and a record of what happens to data. Whether the operator meets its own duties
          under each of these laws depends on how it is run and is for a qualified lawyer to confirm; this page is not that confirmation.
        </p>
      </Section>
      <Section title="Report a problem">
        <p>If you think you have found a weakness, please tell us through <Link to="/support" className="underline underline-offset-4">support</Link> and give us time to fix it before you share it.</p>
      </Section>
    </LegalShell>
  );
}
