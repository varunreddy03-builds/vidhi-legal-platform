import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { apiGet, apiPost } from "@/lib/api";
import { describe } from "@/lib/interaction";
import { LegalShell, Ph, Section } from "@/lib/legal";
import { useMe } from "@/lib/useMe";

const CATEGORIES: [string, string][] = [["general", "A question"], ["bug", "Something is not working"], ["billing", "Billing or payment"], ["privacy", "My data or privacy"], ["other", "Something else"]];

/** Contact support. Works signed in or out; the message is saved and forwarded to the support email the operator has set up. */
export default function Support() {
  const { data: me } = useMe();
  const info = useQuery({ queryKey: ["support-info"], queryFn: () => apiGet<{ email: string | null; whatsapp: string | null }>("/public/support-info"), retry: false });
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [category, setCategory] = useState("general");
  const [message, setMessage] = useState("");
  const [website, setWebsite] = useState(""); // a trap for bots: people never see or fill this
  const [ref, setRef] = useState<string | null>(null);
  const send = useMutation({
    mutationFn: () => apiPost<{ reference: string }>("/public/support", { name: name || me?.full_name || "", email: email || me?.email || "", category, message, website }),
    onSuccess: (r) => {
      setRef(r.reference);
      setMessage("");
    },
    onError: (e) => toast.error(describe(e)),
  });

  return (
    <LegalShell title="Contact support" doc="privacy" testId="support-page">
      <Section title="Write to us">
        {ref ? (
          <p data-testid="support-sent">Thank you. We have your message (reference <strong>{ref}</strong>). We will reply by email.</p>
        ) : (
          <form
            className="space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              send.mutate();
            }}
          >
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="s-name">Your name</Label>
                <Input id="s-name" value={name || me?.full_name || ""} onChange={(e) => setName(e.target.value)} required data-testid="support-name" />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="s-email">Your email</Label>
                <Input id="s-email" type="email" value={email || me?.email || ""} onChange={(e) => setEmail(e.target.value)} required data-testid="support-email" />
              </div>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="s-cat">What is it about?</Label>
              <select id="s-cat" value={category} onChange={(e) => setCategory(e.target.value)} className="h-9 w-full rounded-md border border-border bg-background px-2 text-sm">
                {CATEGORIES.map(([v, l]) => (
                  <option key={v} value={v}>{l}</option>
                ))}
              </select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="s-msg">Your message</Label>
              <Textarea id="s-msg" value={message} onChange={(e) => setMessage(e.target.value)} rows={5} minLength={10} maxLength={4000} required data-testid="support-message" />
              <p className="text-xs text-muted-foreground">Please do not send passwords, card numbers or one-time codes. We will never ask for them. Do not paste your clients' names, case details or documents: we do not need them, and VIDHI never adds anything from your matters to this message. Only what you type here is sent.</p>
            </div>
            <input type="text" name="website" value={website} onChange={(e) => setWebsite(e.target.value)} tabIndex={-1} autoComplete="off" aria-hidden="true" className="absolute -left-[9999px] h-0 w-0 opacity-0" />
            <Button type="submit" loading={send.isPending} data-testid="support-send">Send message</Button>
          </form>
        )}
      </Section>
      <Section title="Other ways to reach us">
        <p>Email: <Ph value={info.data?.email} label="Support email" /></p>
        {info.data?.whatsapp && <p>WhatsApp: {info.data.whatsapp}</p>}
      </Section>
    </LegalShell>
  );
}