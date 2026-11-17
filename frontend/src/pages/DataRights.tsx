import { useEffect, useState } from "react";
import { fileLinkProps } from "@/lib/files";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { apiGet, apiPost } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { describe } from "@/lib/interaction";
import { LegalShell, Ph, Section, useLegalConfig } from "@/lib/legal";
import { useMe } from "@/lib/useMe";

const KINDS: [string, string][] = [
  ["ACCESS", "A copy of the personal data you hold about me"],
  ["CORRECTION", "Correct something that is wrong or out of date"],
  ["ERASURE", "Erase my personal data"],
  ["WITHDRAW_CONSENT", "Withdraw a consent I gave"],
  ["NOMINATION", "Nominate someone to exercise my rights on my behalf"],
  ["GRIEVANCE", "A complaint or grievance about how my data is handled"],
];
type Req = { id: string; kind: string; details: string; status: string; created_at: string; due_by: string };

/** Ask about your data: see it at once, or send a request that is recorded, acknowledged by email and handled by the operator. */
export default function DataRights() {
  const { data: me, isLoading } = useMe();
  const { data: legal } = useLegalConfig();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [kind, setKind] = useState("ACCESS");
  const [details, setDetails] = useState("");
  useEffect(() => {
    if (!isLoading && me === null) navigate("/login?next=/data-rights", { replace: true });
  }, [isLoading, me, navigate]);
  const list = useQuery<Req[]>({ queryKey: ["privacy-requests"], queryFn: () => apiGet<Req[]>("/privacy/requests"), enabled: !!me });
  const send = useMutation({
    mutationFn: () => apiPost<{ note: string }>("/privacy/requests", { kind, details }),
    onSuccess: async (r) => {
      setDetails("");
      await qc.invalidateQueries({ queryKey: ["privacy-requests"] });
      toast.success(r.note || "We received your request and emailed you an acknowledgement.");
    },
    onError: (e) => toast.error(describe(e)),
  });
  if (!me) return null;
  const c = legal?.config ?? {};

  return (
    <LegalShell title="Your data rights" doc="privacy" testId="data-rights-page">
      <Section title="See your data now">
        <p>Download everything we hold about you as a file: your profile, activity, feedback and earlier requests. Passwords and secrets are never included.</p>
        <a {...fileLinkProps("/api/privacy/my-data")} className="inline-block rounded-full border border-border px-4 py-2 text-sm hover:bg-accent" data-testid="download-my-data">
          Download my data
        </a>
      </Section>
      <Section title="Make a request">
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            send.mutate();
          }}
        >
          <fieldset className="space-y-1.5">
            <legend className="sr-only">What do you want to ask for?</legend>
            {KINDS.map(([k, label]) => (
              <label key={k} className="flex items-start gap-2 text-sm">
                <input type="radio" name="kind" value={k} checked={kind === k} onChange={() => setKind(k)} className="mt-1" data-testid={`kind-${k}`} />
                {label}
              </label>
            ))}
          </fieldset>
          <Textarea value={details} onChange={(e) => setDetails(e.target.value)} rows={3} maxLength={2000} placeholder="Anything we should know (optional)" data-testid="request-details" />
          <Button type="submit" loading={send.isPending} data-testid="send-request">
            Send request
          </Button>
        </form>
        <p className="text-xs text-muted-foreground">
          We acknowledge it by email and aim to reply within {legal?.response_days ?? 30} days. That is a service target, not a statement of any legal deadline. Grievance officer:{" "}
          <Ph value={c.grievance_name} label="Grievance officer's name" />, <Ph value={c.privacy_email} label="Privacy contact email" />.
        </p>
      </Section>
      <Section title="Your earlier requests">
        {list.data?.length ? (
          <ul className="space-y-2" data-testid="request-list">
            {list.data.map((r) => (
              <li key={r.id} className="rounded-md border border-border p-3 text-xs">
                <p>
                  {KINDS.find(([k]) => k === r.kind)?.[1] ?? r.kind} <span className="text-muted-foreground">(ref {r.id.slice(0, 8)})</span>
                </p>
                <p className="mt-1 text-muted-foreground">
                  {r.status.replace("_", " ").toLowerCase()} · sent {formatDate(r.created_at)} · reply target {formatDate(r.due_by)}
                </p>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-xs text-muted-foreground">None yet.</p>
        )}
      </Section>
    </LegalShell>
  );
}