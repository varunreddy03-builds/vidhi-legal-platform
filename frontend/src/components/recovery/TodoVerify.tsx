import { needsVerifying, type FactId } from "@/lib/recovery/portalRules";

/** The visible "TODO: verify" mark that goes next to a legal or government fact the guide shows, until the fact is verified in lib/recovery/portalRules.ts. */
export default function TodoVerify({ ids }: { ids: readonly FactId[] }) {
  if (!needsVerifying(ids)) return null;
  return (
    <span className="ml-1.5 whitespace-nowrap rounded px-1.5 py-0.5 text-[11px] font-medium" style={{ color: "#F0A63A", background: "rgba(240,166,58,0.14)" }} data-testid="todo-verify" title="This line has not been checked against the official source yet.">
      TODO: verify
    </span>
  );
}
