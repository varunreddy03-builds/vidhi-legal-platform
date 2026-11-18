import { Link } from "react-router-dom";
import AppShell from "@/components/AppShell";
import { GROUPS, PROMISE } from "@/lib/everything";

/** Everything VIDHI does, in plain words, with what each part cannot do yet. Built from lib/everything.ts, the same list the Start page shows. */
export default function About() {
  return (
    <AppShell title="About VIDHI">
      <div className="mx-auto max-w-4xl vidhi-rise" data-testid="about-page">
        <p className="text-xs uppercase tracking-[0.2em] text-muted-foreground">VIDHI</p>
        <h2 className="mt-1 text-3xl tracking-tight">Everything in VIDHI</h2>
        <p className="mt-2 text-sm text-muted-foreground">
          VIDHI is a legal workspace for lawyers in India. It helps you research, read documents, draft and check your work, and it shows where every answer came from. It is a tool for lawyers: it does not represent anyone or give legal advice.
        </p>
        <p className="mt-2 text-sm font-medium" data-testid="about-promise">{PROMISE}</p>
        <nav aria-label="On this page" className="mt-4 flex flex-wrap gap-2 text-sm">
          {GROUPS.map((g) => <a key={g.id} href={`#about-${g.id}`} className="rounded-full border border-border px-3 py-1 hover:bg-muted">{g.title}</a>)}
        </nav>
        {GROUPS.map((g) => (
          <section key={g.id} id={`about-${g.id}`} className="glass mt-6 rounded-xl p-5 sm:p-6" aria-labelledby={`about-h-${g.id}`} data-testid={`about-${g.id}`}>
            <h3 id={`about-h-${g.id}`} className="text-xl font-medium">{g.title}</h3>
            <p className="mt-1 text-sm text-muted-foreground">{g.intro}</p>
            <ul className="mt-4 space-y-4">
              {g.parts.map((p) => (
                <li key={p.id} data-testid={`about-part-${p.id}`}>
                  <Link to={p.to} className="font-medium underline underline-offset-4">{p.name}</Link>
                  <p className="mt-1 text-sm">{p.what}</p>
                  {p.limit && <p className="mt-1 text-sm text-muted-foreground">Good to know: {p.limit}</p>}
                </li>
              ))}
            </ul>
          </section>
        ))}
        <p className="mt-6 text-sm text-muted-foreground">
          Questions or problems: <Link to="/support" className="underline underline-offset-4">contact support</Link>. Your choices about your data: <Link to="/data-rights" className="underline underline-offset-4">your data rights</Link>.
        </p>
      </div>
    </AppShell>
  );
}
