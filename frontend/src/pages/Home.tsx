import { useRecoveryEnabled } from "@/lib/recovery/useRecoveryEnabled";
import { Link } from "react-router-dom";
import NervousSystemBackground from "@/components/NervousSystemBackground";
import { buttonVariants } from "@/components/ui/button";
import { LanguageMenu, ThemeToggle } from "@/components/AppearanceControls";
import { useT } from "@/lib/i18n/I18nProvider";
import { LegalLinks } from "@/lib/legal";
import { TOOLS } from "@/lib/toolkit";

const PILLARS = [
  ["Sources support", "Every claim maps to a source, a location and a verification status."],
  ["Graphs connect", "Matters, documents, facts and claims form one real, source-backed graph."],
  ["Logic verifies", "Citations are checked, contrary authority surfaced, conflicts never hidden."],
];

export default function Home() {
  const t = useT();
  const { enabled: recoveryOn } = useRecoveryEnabled();
  return (
    <div className="relative min-h-screen">
      <NervousSystemBackground intensity="ambient" />
      <div className="relative z-10">
        <header className="flex h-16 items-center justify-between px-6 md:px-12">
          <span className="font-heading text-sm tracking-[0.3em]">◈ VIDHI</span>
          <div className="flex items-center gap-2">
            <LanguageMenu />
            <ThemeToggle />
            <Link to="/login" className={buttonVariants({ variant: "ghost", size: "sm" })}>
              {t("home.signIn")}
            </Link>
            <Link
              to="/login?mode=signup"
              className={buttonVariants({ size: "sm" })}
              data-testid="landing-get-started"
            >
              {t("home.start")}
            </Link>
          </div>
        </header>

        <main className="mx-auto max-w-5xl px-6 pt-20 pb-24 md:px-12">
          <p className="vidhi-rise text-xs uppercase tracking-[0.35em] text-muted-foreground">
            {t("home.eyebrow")}
          </p>
          <h1 className="vidhi-rise mt-5 max-w-3xl text-4xl leading-[1.05] md:text-6xl">
            {t("home.title1")}
            <span style={{ color: "#5B8CFF" }}> {t("home.title2")}</span>
          </h1>
          <p className="vidhi-rise mt-6 max-w-xl text-base text-muted-foreground">
            {t("home.body")}
          </p>
          <div className="vidhi-rise mt-9 flex flex-wrap gap-3">
            <Link to="/login?mode=signup" className={buttonVariants({ size: "lg" })}>
              {t("home.create")}
            </Link>
            <Link to="/login" className={buttonVariants({ variant: "outline", size: "lg" })}>
              {t("home.have")}
            </Link>
          </div>

          <section className="mt-20" data-testid="home-toolkit">
            <h2 className="font-heading text-lg">{t("home.tk.title")}</h2>
            <p className="mt-1 max-w-2xl text-sm text-muted-foreground">{t("home.tk.sub")}</p>
            <ul className="mt-5 grid gap-4 md:grid-cols-2 lg:grid-cols-3">
              {TOOLS.map((tool) => {
                const Icon = tool.icon;
                return (
                  <li key={tool.id} className="glass flex items-start gap-3 rounded-xl p-5" data-testid={`home-tool-${tool.id}`}>
                    <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-accent">
                      <Icon className="size-4" />
                    </span>
                    <span className="min-w-0">
                      <span className="block text-sm font-medium">{t(tool.title)}</span>
                      <span className="mt-1 block text-xs text-muted-foreground">{t(tool.body)}</span>
                    </span>
                  </li>
                );
              })}
            </ul>
            {recoveryOn && (
              <p className="mt-4 text-xs text-muted-foreground" data-testid="home-recovery-note">
                {t("home.rec.small")}
              </p>
            )}
          </section>

          <div className="mt-10 grid gap-px overflow-hidden rounded-xl border border-border md:grid-cols-3">
            {PILLARS.map(([title, body]) => (
              <div key={title} className="glass p-6">
                <h2 className="font-heading text-sm" style={{ color: "#C8A96B" }}>
                  {title}
                </h2>
                <p className="mt-2 text-sm text-muted-foreground">{body}</p>
              </div>
            ))}
          </div>

          <LegalLinks className="mt-12" />
          <p className="mt-3 text-xs text-muted-foreground" data-testid="landing-disclaimer">
            ⚠️ {t("home.disclaimer")}
          </p>
        </main>
      </div>
    </div>
  );
}
