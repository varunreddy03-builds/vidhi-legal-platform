import { ADVOCATE_TO_CONFIRM, NOTICE_HELP } from "@/lib/recovery/portalRules";

/** The help panel shown above the notice: drafting help. All of its words live in lib/recovery/portalRules.ts. It states no law: each point of law is only
 * named, with "advocate to confirm" beside it. */
export default function NoticeHelp() {
  return (
    <details className="glass rounded-2xl p-4 text-sm" data-testid="notice-help">
      <summary className="cursor-pointer text-base font-medium">{NOTICE_HELP.title}</summary>
      {NOTICE_HELP.sections.map((s) => (
        <section key={s.heading} className="mt-3">
          <h3 className="text-sm font-medium">{s.heading}</h3>
          {s.ordered ? (
            <ol className="mt-1 list-decimal space-y-1 pl-5">
              {s.points.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ol>
          ) : (
            <ul className="mt-1 list-disc space-y-1 pl-5">
              {s.points.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          )}
        </section>
      ))}
      <section className="mt-3" data-testid="notice-help-law">
        <h3 className="text-sm font-medium">{NOTICE_HELP.lawHeading}</h3>
        <p className="mt-1 text-muted-foreground">{NOTICE_HELP.lawIntro}</p>
        <ul className="mt-1 list-disc space-y-1 pl-5">
          {NOTICE_HELP.lawPoints.map((p) => (
            <li key={p}>
              {p}{" "}
              <span className="rounded border px-1 text-xs" data-testid="advocate-to-confirm">
                {ADVOCATE_TO_CONFIRM}
              </span>
            </li>
          ))}
        </ul>
      </section>
    </details>
  );
}
