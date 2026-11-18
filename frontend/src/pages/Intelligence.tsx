import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { BookOpen, CircleCheck, CircleDashed, CircleHelp, FileText, Gavel, Landmark, Library, Search, ShieldCheck, Sparkles, Users, UserSearch, FileStack, Globe } from "lucide-react";
import AppShell from "@/components/AppShell";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { useLawDrafts } from "@/lib/useLawDrafts";
import { useT } from "@/lib/i18n/I18nProvider";
import type { Key } from "@/lib/i18n/en";

const PARTS: { to: string; icon: typeof Gavel; title: Key; body: Key; id: string; tag: string }[] = [
  { to: "/research", icon: Search, title: "nav.research", body: "intel.research.body", id: "research", tag: "Ask with sources" },
  { to: "/matters", icon: Gavel, title: "nav.matters", body: "intel.matters.body", id: "matters", tag: "Cases and documents" },
  { to: "/drafts", icon: FileText, title: "nav.drafts", body: "intel.drafts.body", id: "drafts", tag: "Papers and templates" },
  { to: "/law", icon: Library, title: "nav.law", body: "intel.law.body", id: "law", tag: "Acts and Rules" },
  { to: "/judgments", icon: Landmark, title: "nav.judgments", body: "intel.judgments.body", id: "judgments", tag: "25 High Courts" },
];

const ALSO: { to: string; icon: typeof Gavel; label: string; id: string }[] = [
  { to: "/conflicts", icon: ShieldCheck, label: "Conflict checks", id: "conflicts" },
  { to: "/lawyers", icon: UserSearch, label: "Lawyer directory", id: "lawyers" },
  { to: "/portal", icon: Users, label: "Client portal", id: "portal" },
  { to: "/templates", icon: FileStack, label: "Templates", id: "templates" },
  { to: "/vault", icon: FileStack, label: "Vault", id: "vault" },
  { to: "/tax", icon: FileText, label: "Tax", id: "tax" },
  { to: "/translate", icon: Globe, label: "Translate", id: "translate" },
  { to: "/legal-directory", icon: Landmark, label: "Courts and legal directory", id: "directory" },
  { to: "/connections", icon: Users, label: "Connections", id: "connections" },
  { to: "/about", icon: CircleHelp, label: "Everything in VIDHI", id: "about" },
];

const STATUSES = [
  { icon: CircleCheck, name: "Verified", color: "#3FB68B", text: "The exact words are in a checked source, and a program, not the model, confirmed it." },
  { icon: CircleDashed, name: "Partly verified", color: "#F0A63A", text: "Some support was found, but a gap remains. The answer says what is missing." },
  { icon: CircleHelp, name: "Unsupported", color: "#E5646E", text: "No source backs this claim. It is shown so you can see it, not trust it." },
];

/** Legal Intelligence: ask a question, see how every claim is checked, then go into the parts. */
export default function Intelligence() {
  const t = useT();
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  const acts = useLawDrafts();
  const sections = (acts.data?.acts ?? []).reduce((n, a) => n + a.count, 0);
  const parts = acts.data?.enabled === false ? PARTS.filter((p) => p.id !== "law") : PARTS;
  return (
    <AppShell title={t("nav.intelligence")}>
      <div className="mx-auto max-w-5xl">
        <p className="text-xs uppercase tracking-[0.18em] text-muted-foreground">VIDHI</p>
        <h2 className="mt-1 text-2xl md:text-4xl" data-testid="intel-title">
          {t("nav.intelligence")}
        </h2>
        <p className="mt-2 max-w-2xl text-base text-muted-foreground">{t("intel.sub")}</p>

        <form
          className="glass mt-6 rounded-2xl p-4 md:p-6"
          onSubmit={(e) => {
            e.preventDefault();
            if (q.trim().length >= 3) navigate(`/ask?q=${encodeURIComponent(q.trim())}`);
          }}
        >
          <label htmlFor="intel-q" className="flex items-center gap-2 text-sm text-muted-foreground">
            <Sparkles className="size-4" /> {t("ask.label")}
          </label>
          <Textarea id="intel-q" value={q} onChange={(e) => setQ(e.target.value)} rows={3} className="mt-3 text-base" placeholder={t("ask.placeholder")} data-testid="intel-ask-input" />
          <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
            <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Globe className="size-3.5" /> Ask in your own language. Attach a matter in Research to check answers against its documents.
            </span>
            <Button type="submit" size="lg" disabled={q.trim().length < 3} data-testid="intel-ask-submit">
              <Sparkles /> {t("ask.submit")}
            </Button>
          </div>
        </form>

        <section className="mt-8" aria-label="How every answer is checked" data-testid="intel-checks">
          <h3 className="text-sm font-medium">How every claim in an answer is checked</h3>
          <p className="mt-1 text-sm text-muted-foreground">Each claim gets its own label. The model's opinion never makes a claim verified.</p>
          <div className="mt-3 grid gap-3 sm:grid-cols-3">
            {STATUSES.map((s) => (
              <div key={s.name} className="rounded-xl border border-border p-3">
                <p className="flex items-center gap-2 text-sm font-medium" style={{ color: s.color }}>
                  <s.icon className="size-4" /> {s.name}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">{s.text}</p>
              </div>
            ))}
          </div>
        </section>

        <div className="mt-8 grid gap-4 sm:grid-cols-2" data-testid="intel-parts">
          {parts.map((p) => (
            <Link key={p.id} to={p.to} className="glass glass-lift flex gap-4 rounded-2xl p-5" data-testid={`intel-${p.id}`}>
              <p.icon className="mt-1 size-5 shrink-0 text-muted-foreground" />
              <span>
                <span className="block text-xs uppercase tracking-wider text-muted-foreground">{p.tag}</span>
                <span className="mt-0.5 block text-lg">{t(p.title)}</span>
                <span className="mt-1 block text-sm text-muted-foreground">{t(p.body)}</span>
                {p.id === "law" && sections > 0 && (
                  <span className="mt-2 inline-flex items-center gap-1 text-xs text-muted-foreground" data-testid="intel-law-count">
                    <BookOpen className="size-3.5" /> {sections.toLocaleString()} sections, not reviewed yet
                  </span>
                )}
              </span>
            </Link>
          ))}
        </div>

        <section className="mt-8" aria-label="Also in Legal Intelligence">
          <h3 className="text-sm font-medium">Also here</h3>
          <div className="mt-3 flex flex-wrap gap-2" data-testid="intel-also">
            {ALSO.map((a) => (
              <Link key={a.id} to={a.to} className="inline-flex items-center gap-2 rounded-full border border-border px-3 py-1.5 text-sm hover:bg-muted" data-testid={`intel-also-${a.id}`}>
                <a.icon className="size-4 text-muted-foreground" /> {a.label}
              </Link>
            ))}
          </div>
        </section>

        <p className="mt-8 text-sm text-muted-foreground">{t("ask.disclaimer")}</p>
      </div>
    </AppShell>
  );
}
