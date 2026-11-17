import { Link } from "react-router-dom";
import { LegalShell, Ph, Section, useLegalConfig } from "@/lib/legal";

/** Terms of service DRAFT for a qualified Indian lawyer to review. Bracketed items are decisions or details only the operator and counsel can supply. */
export default function Terms() {
  const { data } = useLegalConfig();
  const c = data?.config ?? {};
  return (
    <LegalShell title="Terms of service" doc="terms" testId="terms-page">
      <Section title="1. Who we are and what this is">
        <p>
          VIDHI is provided by <Ph value={c.legal_name} label="Legal entity name" />, <Ph value={c.registered_address} label="Registered address" /> (&ldquo;we&rdquo;). By creating an account or using VIDHI you agree to these terms
          and to our <Link to="/privacy" className="underline underline-offset-4">Privacy policy</Link>. If you do not agree, please do not use it.
        </p>
      </Section>
      <Section title="2. VIDHI is a tool, not a lawyer">
        <p>VIDHI helps you research, organise and draft. It does not give legal advice and no lawyer-client relationship is created by using it. AI output can be wrong or incomplete. A legal point is shown as verified only when its exact text is in our reviewed library; everything else is shown as unverified. Check anything important with a qualified lawyer before you rely on it or act on it.</p>
        <p>Legal Recovery helps ordinary people and businesses prepare notices and records for money they say they are owed. It does not send anything for you without your approval, and a notice is only as accurate as the facts you provide.</p>
      </Section>
      <Section title="3. Your account">
        <p>Give accurate information, keep your password and sign-in codes private, and tell us if you think someone else has used your account. You are responsible for what happens under it. Organisation owners are responsible for the people they invite. VIDHI is for people aged 18 or over.</p>
      </Section>
      <Section title="4. What you may and may not do">
        <p>Use VIDHI lawfully. Do not upload material you have no right to use or share, or that you must not send to the AI and other services listed in the Privacy policy. Do not try to break, overload or probe the service, to get around its limits or security, or to use it to harass, threaten or deceive anyone. Do not use it to prepare documents that falsely claim to come from a court, authority or lawyer. We may suspend an account that does.</p>
      </Section>
      <Section title="5. Your content">
        <p>You keep ownership of what you upload and create. You give us permission to store and process it, including by the services in the Privacy policy, only to run VIDHI for you. You confirm you are entitled to give that permission.</p>
      </Section>
      <Section title="6. Plans, payment and cancelling">
        <p>Legal Recovery is free. The rest of VIDHI has a free plan with limits and a paid Pro plan. The price, currency and billing period are shown before you pay, and payment is taken on the pages of Stripe, Razorpay or PayPal. Pro renews until you cancel; cancelling stops the next renewal and Pro continues to the end of the period already paid for.</p>
        <p>Refunds: <Ph label="Refund policy" /> (to be set by the operator; the product can issue refunds). Taxes: <Ph value={c.gstin} label="GST number (if registered)" /> (the operator will confirm what tax applies and how invoices are issued).</p>
      </Section>
      <Section title="7. Availability and changes">
        <p>We work to keep VIDHI available but do not promise it will always be uninterrupted or error-free. AI features may pause, for example when a monthly usage limit is reached. We may change or remove features, and we will give notice of changes that matter.</p>
      </Section>
      <Section title="8. Our responsibility">
        <p>
          Nothing in these terms limits responsibility that cannot lawfully be limited. Subject to that, VIDHI is provided as it is, and <Ph label="Limitation of liability wording" /> (counsel to settle: what we are and are not liable for, and any cap).
        </p>
      </Section>
      <Section title="9. Ending your use">
        <p>You can stop at any time and an owner can erase the organisation (Settings). We may suspend or end access for breach of these terms or to protect the service or other people, and will say why where we are able to.</p>
      </Section>
      <Section title="10. Law and disputes">
        <p><Ph label="Governing law, courts and dispute process" /> (to be set by counsel for the operator&apos;s actual arrangements). Until then, nothing here removes any right you have under the law that applies to you.</p>
      </Section>
      <Section title="11. Contact and complaints">
        <p>
          Support: <Ph value={c.support_email} label="Support email" />, or <Link to="/support" className="underline underline-offset-4">contact form</Link>. Grievance officer:{" "}
          <Ph value={c.grievance_name} label="Grievance officer's name" />, <Ph value={c.grievance_email} label="Grievance officer's email" />. To use your data rights, see{" "}
          <Link to="/data-rights" className="underline underline-offset-4">Your data rights</Link>.
        </p>
      </Section>
    </LegalShell>
  );
}