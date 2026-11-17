import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import AppShell from "@/components/AppShell";
import { Input } from "@/components/ui/input";
import { apiGet } from "@/lib/api";
import { useT } from "@/lib/i18n/I18nProvider";

type Entry = {
  id: string;
  section: string;
  name: string;
  what: string;
  law?: string | null;
  note?: string | null;
  official: boolean;
  app_link?: string | null;
  url: string | null;
  link_status: "ok" | "none" | "not_confirmed" | "not_official";
  link_note?: string;
  checked_on?: string;
  government_domain?: boolean;
  listed_on?: string | null;
  states?: string[];
};
type DirectoryAnswer = { items: Entry[]; sections: { id: string; title: string }[]; note: string; links_checked_on: string | null; lists_read_on: string | null };
type StateBody = { state: string; name: string; office_phone: string | null; source: string; read_on: string; url: string | null; link_note?: string; checked_on?: string; district_note: string };
type AidAnswer = { note: string; national: Entry[]; state: StateBody | null; states: string[]; source: string };

function host(u: string): string {
  try {
    return new URL(u).hostname.replace(/^www\./, "");
  } catch {
    return u;
  }
}

/** One address, shown only when the server says it was checked and is official. Opens in a new tab; the site's name is shown so the reader sees where the link goes. */
function OfficialLink({ url, checkedOn, listedOn, testId }: { url: string; checkedOn?: string; listedOn?: string | null; testId: string }) {
  return (
    <p className="mt-1 text-sm">
      <a href={url} target="_blank" rel="noopener noreferrer" className="underline" data-testid={testId}>
        {host(url)}
      </a>
      <span className="text-muted-foreground">
        {" "}
        (opens the official site{checkedOn ? `; address checked on ${checkedOn}` : ""}
        {listedOn ? `; listed on ${host(listedOn)}` : ""})
      </span>
    </p>
  );
}

function EntryCard({ e }: { e: Entry }) {
  return (
    <li className="rounded-lg border border-border p-3" data-testid={`dir-entry-${e.id}`}>
      <h4 className="font-medium">
        {e.name}
        {!e.official && <span className="ml-2 rounded bg-muted px-1.5 py-0.5 text-xs font-normal text-muted-foreground">private, not official</span>}
      </h4>
      <p className="mt-1 text-sm">{e.what}</p>
      {e.law && <p className="mt-1 text-sm text-muted-foreground">Law: {e.law}</p>}
      {e.states && e.states.length > 0 && <p className="mt-1 text-sm text-muted-foreground">Serves: {e.states.join(", ")}</p>}
      {e.note && <p className="mt-1 text-sm text-muted-foreground">{e.note}</p>}
      {e.url && <OfficialLink url={e.url} checkedOn={e.checked_on} listedOn={e.listed_on} testId={`dir-link-${e.id}`} />}
      {!e.url && e.link_note && <p className="mt-1 text-sm text-muted-foreground" data-testid={`dir-nolink-${e.id}`}>{e.link_note}</p>}
      {e.url && e.link_note && <p className="mt-1 text-sm text-muted-foreground">{e.link_note}</p>}
      {e.app_link && (
        <p className="mt-1 text-sm">
          <Link to={e.app_link} className="underline">
            Open in VIDHI
          </Link>
        </p>
      )}
    </li>
  );
}

/** A directory that points to courts, official portals, law reports, court rules and legal aid bodies. It gives no legal advice and shows only addresses the server has checked. */
export default function LegalDirectory() {
  const t = useT();
  const [q, setQ] = useState("");
  const [section, setSection] = useState("");
  const [state, setState] = useState("");
  const list = useQuery<DirectoryAnswer>({ queryKey: ["legal-directory", q.trim(), section], queryFn: () => apiGet(`/legal-directory?q=${encodeURIComponent(q.trim())}&section=${encodeURIComponent(section)}`) });
  const aid = useQuery<AidAnswer>({ queryKey: ["legal-directory-aid", state], queryFn: () => apiGet(`/legal-directory/legal-aid?state=${encodeURIComponent(state)}`) });
  const sections = list.data?.sections ?? [];
  const items = list.data?.items ?? [];
  const body = aid.data?.state;
  return (
    <AppShell title={t("nav.legaldir")}>
      <div className="mx-auto max-w-4xl">
        <h2 className="text-2xl md:text-3xl" data-testid="dir-title">
          {t("nav.legaldir")}
        </h2>
        <p className="mt-2 text-sm text-muted-foreground" data-testid="dir-note">
          Where to find courts, official portals, Acts, law reports, court rules and legal aid. {list.data?.note ?? ""}
          {list.data?.links_checked_on ? ` Addresses were last checked on ${list.data.links_checked_on}.` : ""}
        </p>

        <section className="mt-5 rounded-lg border border-border p-4" aria-labelledby="dir-aid-h" data-testid="dir-aid">
          <h3 id="dir-aid-h" className="text-lg">
            Need a lawyer and cannot afford one?
          </h3>
          <p className="mt-1 text-sm">{aid.data?.note ?? ""}</p>
          <label className="mt-3 block text-sm" htmlFor="dir-state">
            Your State or Union Territory
          </label>
          <select id="dir-state" value={state} onChange={(e) => setState(e.target.value)} className="mt-1 h-10 max-w-full rounded-md border border-border bg-background px-2 text-sm" data-testid="dir-state">
            <option value="">Choose…</option>
            {(aid.data?.states ?? []).map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          {body && (
            <div className="mt-3" data-testid="dir-state-body">
              <p className="font-medium">{body.name}</p>
              {body.office_phone && <p className="mt-1 text-sm">Office phone: {body.office_phone}</p>}
              {body.url && <OfficialLink url={body.url} checkedOn={body.checked_on} testId="dir-state-link" />}
              {body.link_note && <p className="mt-1 text-sm text-muted-foreground">{body.link_note}</p>}
              <p className="mt-1 text-sm text-muted-foreground">{body.district_note}</p>
              <p className="mt-1 text-sm text-muted-foreground">
                As listed in NALSA&apos;s directory, read on {body.read_on}. Phone numbers change: confirm on the authority&apos;s own site.
              </p>
            </div>
          )}
          <ul className="mt-3 grid gap-2">
            {(aid.data?.national ?? []).map((e) => (
              <EntryCard key={e.id} e={e} />
            ))}
          </ul>
        </section>

        <div className="mt-6 flex flex-wrap gap-2">
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search the directory, for example: revenue, consumer, gazette" aria-label="Search the directory" className="min-w-0 flex-1" data-testid="dir-search" />
          <select value={section} onChange={(e) => setSection(e.target.value)} aria-label="Section" className="h-10 max-w-full rounded-md border border-border bg-background px-2 text-sm" data-testid="dir-section">
            <option value="">All sections</option>
            {sections.map((s) => (
              <option key={s.id} value={s.id}>
                {s.title}
              </option>
            ))}
          </select>
        </div>
        {list.isLoading && <p className="mt-4 text-sm text-muted-foreground">Loading…</p>}
        {!list.isLoading && items.length === 0 && (
          <p className="mt-4 text-sm text-muted-foreground" data-testid="dir-empty">
            Nothing found. Try other words.
          </p>
        )}
        {sections
          .filter((s) => s.id !== "legal_aid" && items.some((i) => i.section === s.id))
          .map((s) => (
            <section key={s.id} className="mt-6" aria-labelledby={`dir-h-${s.id}`} data-testid={`dir-section-${s.id}`}>
              <h3 id={`dir-h-${s.id}`} className="text-lg">
                {s.title}
              </h3>
              <ul className="mt-2 grid gap-2">
                {items
                  .filter((i) => i.section === s.id)
                  .map((e) => (
                    <EntryCard key={e.id} e={e} />
                  ))}
              </ul>
            </section>
          ))}
      </div>
    </AppShell>
  );
}
