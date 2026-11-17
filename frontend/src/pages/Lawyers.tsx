import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import NervousSystemBackground from "@/components/NervousSystemBackground";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, apiGet, apiPost } from "@/lib/api";
import { describe } from "@/lib/interaction";
import { LegalLinks } from "@/lib/legal";

interface Info { enabled: boolean; practice_areas: string[]; languages: string[]; notice: string; turnstile_site_key: string | null }
interface Lawyer { id: string; display_name: string; city: string; state: string; practice_areas: string[]; languages: string[]; bio: string; enrolment_claim: string; accepting_requests: boolean }
const LANG_NAME = (code: string) => { try { return new Intl.DisplayNames(["en"], { type: "language" }).of(code) ?? code; } catch { return code; } };

function Shell({ children, title }: { children: React.ReactNode; title: string }) {
  return (
    <main id="main-content" className="relative min-h-screen px-4 py-10">
      <NervousSystemBackground intensity="ambient" />
      <div className="glass relative z-10 mx-auto max-w-3xl space-y-5 rounded-xl p-8" data-testid="lawyers-page">
        <Link to="/" className="font-heading text-xs tracking-[0.3em] text-muted-foreground">◈ VIDHI</Link>
        <h1 className="text-2xl">{title}</h1>
        {children}
        <LegalLinks className="border-t border-border pt-4" />
      </div>
    </main>
  );
}

/** Public list of lawyers who chose to be listed. Alphabetical, never ranked. Answers 404 (shown as "not available") while the switch is off. */
export default function Lawyers() {
  const info = useQuery({ queryKey: ["dir-info"], queryFn: () => apiGet<Info>("/public/directory"), retry: false });
  const [area, setArea] = useState("");
  const [language, setLanguage] = useState("");
  const [city, setCity] = useState("");
  const qs = new URLSearchParams({ ...(area && { area }), ...(language && { language }), ...(city.trim() && { city: city.trim() }) }).toString();
  const list = useQuery({ queryKey: ["lawyers", qs], queryFn: () => apiGet<{ items: Lawyer[]; total: number; notice: string }>(`/public/lawyers?${qs}`), enabled: !!info.data?.enabled, retry: false });
  const select = "h-9 w-full rounded-md border border-border bg-background px-2 text-sm";

  if (info.data && !info.data.enabled) return <Shell title="Lawyer directory"><p className="text-sm text-muted-foreground" data-testid="directory-off">The lawyer directory is not available.</p></Shell>;
  return (
    <Shell title="Find a lawyer">
      <p className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm" role="note">{info.data?.notice}</p>
      <div className="grid gap-3 sm:grid-cols-3">
        <div className="space-y-1.5"><Label htmlFor="l-area">Area of law</Label>
          <select id="l-area" className={select} value={area} onChange={(e) => setArea(e.target.value)}><option value="">Any</option>{info.data?.practice_areas.map((a) => <option key={a}>{a}</option>)}</select></div>
        <div className="space-y-1.5"><Label htmlFor="l-lang">Language</Label>
          <select id="l-lang" className={select} value={language} onChange={(e) => setLanguage(e.target.value)}><option value="">Any</option>{info.data?.languages.map((l) => <option key={l} value={l}>{LANG_NAME(l)}</option>)}</select></div>
        <div className="space-y-1.5"><Label htmlFor="l-city">City</Label><Input id="l-city" value={city} onChange={(e) => setCity(e.target.value)} placeholder="e.g. Hyderabad" /></div>
      </div>
      <div className="space-y-3" data-testid="lawyer-list">
        {(list.data?.items ?? []).map((l) => (
          <Link key={l.id} to={`/lawyers/${l.id}`} className="glass block rounded-lg p-4" data-testid="lawyer-card">
            <p className="font-medium">{l.display_name}</p>
            <p className="text-sm text-muted-foreground">{[l.city, l.state].filter(Boolean).join(", ")} · {l.practice_areas.join(", ")}</p>
          </Link>
        ))}
        {list.isSuccess && list.data.items.length === 0 && <p className="text-sm text-muted-foreground">No lawyers match. Listing is voluntary, so the list may be short.</p>}
      </div>
    </Shell>
  );
}

export function LawyerProfile() {
  const { id = "" } = useParams();
  const info = useQuery({ queryKey: ["dir-info"], queryFn: () => apiGet<Info>("/public/directory"), retry: false });
  const one = useQuery({ queryKey: ["lawyer", id], queryFn: () => apiGet<Lawyer & { notice: string }>(`/public/lawyers/${id}`), retry: false });
  const opened = useRef(Date.now());
  const widget = useRef<HTMLDivElement>(null);
  const [token, setToken] = useState<string | null>(null);
  const [f, setF] = useState({ name: "", email: "", phone: "", message: "", consent: false, website: "" });
  const [sent, setSent] = useState<string | null>(null);
  const siteKey = info.data?.turnstile_site_key ?? null;

  useEffect(() => {
    if (!siteKey || !widget.current || !one.data) return;
    const el = widget.current;
    const render = () => (window as unknown as { turnstile?: { render: (e: HTMLElement, o: object) => void } }).turnstile?.render(el, { sitekey: siteKey, callback: (t: string) => setToken(t), "expired-callback": () => setToken(null) });
    if ((window as unknown as { turnstile?: unknown }).turnstile) return render();
    const s = document.createElement("script");
    s.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
    s.async = true;
    s.onload = render;
    document.head.appendChild(s);
  }, [siteKey, one.data]);

  const send = useMutation({
    mutationFn: () => apiPost<{ message: string }>(`/public/lawyers/${id}/requests`, { ...f, elapsed_ms: Date.now() - opened.current, ...(token ? { turnstile_token: token } : {}) }),
    onSuccess: (r) => setSent(r.message),
    onError: (e) => toast.error(describe(e)),
  });

  if (one.error instanceof ApiError || (info.data && !info.data.enabled)) return <Shell title="Lawyer"><p className="text-sm text-muted-foreground">This lawyer is not available.</p></Shell>;
  const l = one.data;
  return (
    <Shell title={l?.display_name ?? "Lawyer"}>
      {l && (
        <>
          <p className="text-sm text-muted-foreground">{[l.city, l.state].filter(Boolean).join(", ")}</p>
          <p className="text-sm">{l.practice_areas.join(" · ")}{l.languages.length > 0 && <span className="text-muted-foreground"> · Languages: {l.languages.map(LANG_NAME).join(", ")}</span>}</p>
          {l.bio && <p className="whitespace-pre-wrap text-sm">{l.bio}</p>}
          {l.enrolment_claim && <p className="text-xs text-muted-foreground">Enrolment number as stated by the lawyer: {l.enrolment_claim} (not verified by VIDHI)</p>}
          <p className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm" role="note">{l.notice}</p>
          {sent ? (
            <p data-testid="request-sent">{sent}</p>
          ) : l.accepting_requests ? (
            <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); send.mutate(); }} data-testid="request-form">
              <h2 className="text-lg">Send a consultation request</h2>
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="space-y-1.5"><Label htmlFor="r-name">Your name</Label><Input id="r-name" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} required maxLength={100} /></div>
                <div className="space-y-1.5"><Label htmlFor="r-email">Your email</Label><Input id="r-email" type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} required /></div>
                <div className="space-y-1.5"><Label htmlFor="r-phone">Phone (optional)</Label><Input id="r-phone" value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} maxLength={20} /></div>
              </div>
              <div className="space-y-1.5"><Label htmlFor="r-msg">What do you need help with?</Label><Textarea id="r-msg" rows={5} minLength={20} maxLength={1500} value={f.message} onChange={(e) => setF({ ...f, message: e.target.value })} required /><p className="text-xs text-muted-foreground">Keep it short. Do not include passwords, card numbers or confidential documents.</p></div>
              <input type="text" name="website" value={f.website} onChange={(e) => setF({ ...f, website: e.target.value })} tabIndex={-1} autoComplete="off" aria-hidden="true" className="absolute -left-[9999px] h-0 w-0 opacity-0" />
              {siteKey && <div ref={widget} />}
              <label className="flex items-start gap-2 text-sm"><input type="checkbox" className="mt-1" checked={f.consent} onChange={(e) => setF({ ...f, consent: e.target.checked })} data-testid="request-consent" />I understand this is not legal advice and does not make this person my lawyer.</label>
              <Button type="submit" loading={send.isPending} disabled={!f.consent || (!!siteKey && !token)} data-testid="request-send">Send request</Button>
            </form>
          ) : (
            <p className="text-sm text-muted-foreground">This lawyer is not taking requests through VIDHI right now.</p>
          )}
        </>
      )}
    </Shell>
  );
}