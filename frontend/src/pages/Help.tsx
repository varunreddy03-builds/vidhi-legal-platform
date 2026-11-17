import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import AppShell from "@/components/AppShell";
import { Input } from "@/components/ui/input";
import { useI18n } from "@/lib/i18n/I18nProvider";
import { HELP_LANGUAGES, hasHelp, useHelp } from "@/lib/help/useHelp";
import { LANGUAGE_BY_CODE } from "@/lib/languages";
import en from "@/lib/help/en";

/** Frequently asked questions, in English, Hindi, Telugu, Tamil, Bengali, Marathi and Gujarati. Informational only: it is not legal advice, and every
 *  language except English is a translation that no native speaker has reviewed yet (the page says so). */
export default function Help() {
  const { lang } = useI18n();
  const [pick, setPick] = useState<string>(hasHelp(lang) ? lang : "en");
  const [q, setQ] = useState("");
  const h = useHelp(pick);
  const needle = q.trim().toLowerCase();
  const match = (s: { title: string; items: { q: string; a: string }[] }) => ({ ...s, items: s.items.filter((i) => !needle || (i.q + " " + i.a).toLowerCase().includes(needle)) });
  const sections = useMemo(() => h.sections.map(match).filter((s) => s.items.length), [h, needle]); // eslint-disable-line react-hooks/exhaustive-deps
  // pages that exist in English only so far: shown to everyone after the translated ones, under a line that says so
  const extra = useMemo(() => (en.extra ?? []).map(match).filter((s) => s.items.length), [needle]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <AppShell title={h.ui.helpCentre}>
      <div className="mx-auto max-w-3xl space-y-6" data-testid="help-page">
        <p className="text-sm text-muted-foreground" data-testid="help-pilot-feedback">
          Testing VIDHI in the pilot?{" "}
          <Link to="/feedback" className="underline underline-offset-2">
            Give pilot feedback
          </Link>
          .
        </p>
        <div className="flex flex-wrap items-end justify-between gap-3">
          <h2 className="text-2xl">{h.ui.helpCentre}</h2>
          <label className="flex items-center gap-2 text-sm">
            <span className="text-muted-foreground">{h.ui.language}</span>
            <select value={pick} onChange={(e) => setPick(e.target.value)} className="h-9 rounded-md border border-border bg-background px-2" data-testid="help-language">
              {HELP_LANGUAGES.map((c) => (
                <option key={c} value={c}>{LANGUAGE_BY_CODE.get(c)?.native ?? c}</option>
              ))}
            </select>
          </label>
        </div>
        {h.note && <p className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm" role="note" data-testid="help-note">{h.note}</p>}
        <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder={h.ui.search} aria-label={h.ui.search} />
        {sections.map((s) => (
          <section key={s.title} className="space-y-2">
            <h3 className="text-lg">{s.title}</h3>
            {s.items.map((i) => (
              <details key={i.q} className="glass rounded-lg p-3" data-testid="help-item">
                <summary className="block cursor-pointer py-2 text-sm font-medium">{i.q}</summary>
                <p className="mt-2 text-sm text-muted-foreground">{i.a}</p>
              </details>
            ))}
          </section>
        ))}
        {extra.length > 0 && (
          <p className="pt-2 text-sm text-muted-foreground" lang="en" data-testid="help-english-only">
            The pages below are in English only so far.
          </p>
        )}
        {extra.map((s) => (
          <section key={s.title} className="space-y-2" lang="en">
            <h3 className="text-lg">{s.title}</h3>
            {s.items.map((i) => (
              <details key={i.q} className="glass rounded-lg p-3" data-testid="help-item-extra">
                <summary className="block cursor-pointer py-2 text-sm font-medium">{i.q}</summary>
                <p className="mt-2 text-sm text-muted-foreground">{i.a}</p>
              </details>
            ))}
          </section>
        ))}
        {sections.length === 0 && extra.length === 0 && <p className="text-sm text-muted-foreground">{h.ui.noResults}</p>}
        <p className="text-sm"><Link to="/support" className="underline underline-offset-4">{h.ui.contact}</Link></p>
      </div>
    </AppShell>
  );
}