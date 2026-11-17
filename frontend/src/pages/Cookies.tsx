import { Link } from "react-router-dom";
import { LegalShell, Section } from "@/lib/legal";

/** Cookie policy DRAFT. It lists exactly what the software stores in the browser (kept in step with the code); counsel reviews the wording. */
const ROWS: [string, string, string, string][] = [
  ["vidhi_session", "Cookie", "Keeps you signed in", "Up to 30 days; renewed while you use the app. Essential."],
  ["vidhi_oauth", "Cookie", "Protects the Google sign-in step from being hijacked", "10 minutes. Only set if you choose Google sign-in. Essential."],
  ["vidhi-theme, vidhi-lang", "Browser storage", "Remembers dark or light mode and your language", "Until you clear your browser data. Preference."],
  ["vidhi-pending-payment", "Browser storage", "Lets you check a payment you just made on Razorpay's page", "Until the payment is confirmed. Essential to that step."],
  ["vidhi-tour", "Browser storage", "Remembers that you have seen or skipped the first-time tour", "Until you clear your browser data. Preference."],
  ["Notification subscription", "Browser and its push service", "Lets VIDHI send a reminder about a date you saved to this device (only if you turn notifications on)", "Until you turn notifications off here or in your browser. Optional."],
];

export default function Cookies() {
  return (
    <LegalShell title="Cookie policy" doc="cookies" testId="cookies-page">
      <Section title="In short">
        <p>VIDHI uses only what it needs to work. There are no advertising cookies, no analytics or tracking cookies, and nothing is shared with advertisers.</p>
      </Section>
      <Section title="What is stored in your browser">
        <div className="overflow-x-auto focus-visible:outline-2 focus-visible:outline-offset-2" tabIndex={0} role="region" aria-label="Cookies and browser storage used by VIDHI (scrolls sideways on a small screen)">
          <table className="w-full text-left text-xs">
            <thead className="text-muted-foreground">
              <tr><th className="py-1 pr-3">Name</th><th className="pr-3">Kind</th><th className="pr-3">Why</th><th>How long</th></tr>
            </thead>
            <tbody>
              {ROWS.map(([name, kind, why, how]) => (
                <tr key={name} className="border-t border-border align-top">
                  <td className="py-1.5 pr-3 font-mono">{name}</td><td className="pr-3">{kind}</td><td className="pr-3">{why}</td><td>{how}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>
      <Section title="Third-party pages">
        <p>When you pay, you are sent to the page of Stripe, Razorpay or PayPal, and when you choose Google sign-in to Google&apos;s page. Those companies set their own cookies there under their own policies.</p>
      </Section>
      <Section title="Your choice">
        <p>You can delete these in your browser settings. If you delete the sign-in cookie you will be signed out. If analytics or any non-essential cookie is ever added, this page will be updated and your consent will be asked first. More about your data: <Link to="/privacy" className="underline underline-offset-4">Privacy policy</Link>.</p>
      </Section>
    </LegalShell>
  );
}