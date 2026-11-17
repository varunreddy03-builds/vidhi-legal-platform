import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import AppShell from "@/components/AppShell";
import { apiGet } from "@/lib/api";
import { useT } from "@/lib/i18n/I18nProvider";
import { TOOLS } from "@/lib/toolkit";

// All five tools are built, and only the server can switch each on. A tool that is not switched on shows a plain notice: no buttons, no pretend results.

/** Legal Katalyst: checks a lawyer runs on their own work before it goes out. */
export default function Toolkit() {
  const t = useT();
  // Authority Check answers 404 until the server switches it on (AUTHORITY_CHECK_ENABLED); only then does its card become a link
  const authorityOn = useQuery({ queryKey: ["authority-on"], queryFn: () => apiGet("/authority/checks").then(() => true), retry: false, staleTime: 60_000 }).data === true;
  // the list of dates answers 404 until the server switches it on (DATE_LIST_ENABLED)
  const datesOn = useQuery({ queryKey: ["datelists-on"], queryFn: () => apiGet("/datelists").then(() => true), retry: false, staleTime: 60_000 }).data === true;
  // the pre-filing defect check answers 404 until the server switches it on (DEFECT_CHECK_ENABLED)
  const defectsOn = useQuery({ queryKey: ["defectchecks-on"], queryFn: () => apiGet("/defectchecks").then(() => true), retry: false, staleTime: 60_000 }).data === true;
  // the old-code checker answers 404 until the server switches it on (OLD_CODE_CHECK_ENABLED)
  const oldcodeOn = useQuery({ queryKey: ["oldcodechecks-on"], queryFn: () => apiGet("/oldcodechecks").then(() => true), retry: false, staleTime: 60_000 }).data === true;
  // the deadline engine answers 404 until the server switches it on (DEADLINE_ENGINE_ENABLED)
  const deadlinesOn = useQuery({ queryKey: ["deadline-rules-on"], queryFn: () => apiGet("/deadline-rules").then(() => true), retry: false, staleTime: 60_000 }).data === true;
  const built: Record<string, { on: boolean; to: string }> = {
    authority: { on: authorityOn, to: "/katalyst/authority" },
    dates: { on: datesOn, to: "/katalyst/dates" },
    defects: { on: defectsOn, to: "/katalyst/defects" },
    oldcode: { on: oldcodeOn, to: "/katalyst/oldcode" },
    deadlines: { on: deadlinesOn, to: "/katalyst/deadlines" },
  };
  return (
    <AppShell title={t("nav.toolkit")}>
      <div className="mx-auto max-w-3xl">
        <h2 className="text-2xl md:text-3xl" data-testid="toolkit-title">
          {t("nav.toolkit")}
        </h2>
        <p className="mt-2 text-sm text-muted-foreground">{t("toolkit.sub")}</p>
        <ul className="mt-6 grid gap-4" data-testid="toolkit-list">
          {TOOLS.map((tool, i) => {
            const Icon = tool.icon;
            const state = built[tool.id];
            const live = state?.on === true;
            const card = (
              <>
                <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-accent">
                  <Icon className="size-5" style={{ color: i === 0 ? "#C8A96B" : undefined }} />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex flex-wrap items-center gap-2">
                    <span className="text-base">{t(tool.title)}</span>
                    <span
                      className="rounded-full border border-border px-2 py-0.5 text-[11px] text-muted-foreground"
                      data-testid={`toolkit-${tool.id}-state`}
                    >
                      {state ? (state.on ? "Ready" : t("toolkit.off")) : t("toolkit.soon")}
                    </span>
                  </span>
                  <span className="mt-1 block text-sm text-muted-foreground">{t(tool.body)}</span>
                </span>
              </>
            );
            return (
              <li key={tool.id} data-testid={`toolkit-${tool.id}`}>
                {live ? (
                  <Link to={state.to} className="glass glass-lift flex items-start gap-4 rounded-2xl p-5">
                    {card}
                  </Link>
                ) : (
                  <div className="glass flex items-start gap-4 rounded-2xl p-5 opacity-90">{card}</div>
                )}
              </li>
            );
          })}
        </ul>
        <p className="mt-6 text-xs text-muted-foreground">{t("toolkit.note")}</p>
      </div>
    </AppShell>
  );
}
