import type { ComponentType, ReactNode } from "react";
import { Link } from "react-router-dom";
import { ArrowRight } from "lucide-react";

/**
 * A "door": one big, obvious choice. Used on the start screen and the front page so that nobody has to learn
 * the app's vocabulary before they can begin. The light follows the pointer.
 */
export default function Door({
  to,
  icon: Icon,
  tag,
  tagTone = "gold",
  title,
  children,
  cta,
  testId,
  accent = "#C8A96B",
}: {
  to: string;
  icon: ComponentType<{ className?: string; style?: React.CSSProperties }>;
  tag?: string;
  tagTone?: "gold" | "blue";
  title: string;
  children: ReactNode;
  cta: string;
  testId?: string;
  accent?: string;
}) {
  return (
    <Link
      to={to}
      data-testid={testId}
      className="door glass glass-lift group flex flex-col rounded-2xl p-4 md:min-h-[15rem] md:p-7"
      onMouseMove={(e) => {
        const r = e.currentTarget.getBoundingClientRect();
        e.currentTarget.style.setProperty("--mx", `${e.clientX - r.left}px`);
        e.currentTarget.style.setProperty("--my", `${e.clientY - r.top}px`);
      }}
    >
      <div className="flex items-start justify-between gap-3">
        <span
          className="grid size-11 place-items-center rounded-2xl border md:size-14"
          style={{ borderColor: `${accent}55`, background: `${accent}14`, boxShadow: `0 0 28px -8px ${accent}88` }}
        >
          <Icon className="size-6 md:size-7" style={{ color: accent }} />
        </span>
        {tag && (
          <span
            className="shrink-0 whitespace-nowrap rounded-full border px-3 py-1 text-xs"
            style={
              tagTone === "blue"
                ? { color: "#5B8CFF", borderColor: "#5B8CFF55", background: "#5B8CFF14" }
                : { color: "#C8A96B", borderColor: "#C8A96B55", background: "#C8A96B14" }
            }
          >
            {tag}
          </span>
        )}
      </div>
      <h3 className="mt-3 text-xl md:mt-5 md:text-2xl">{title}</h3>
      <p className="mt-2 flex-1 text-sm text-muted-foreground md:text-base">{children}</p>
      <span className="mt-3 inline-flex items-center gap-2 text-sm font-medium md:mt-5" style={{ color: accent }}>
        {cta}
        <ArrowRight className="size-4 transition-transform duration-300 group-hover:translate-x-1.5" />
      </span>
    </Link>
  );
}
