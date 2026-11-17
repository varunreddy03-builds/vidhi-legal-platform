import { useState } from "react";
import { fileLinkProps } from "@/lib/files";
import { useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { apiGet, apiPost } from "@/lib/api";
import { formatDate, formatDateTime } from "@/lib/format";
import { describe } from "@/lib/interaction";
import type { DeliveryInfo } from "@/lib/types";
import { useCan } from "@/lib/useMe";

const CHANNELS = [
  ["WHATSAPP", "WhatsApp"],
  ["EMAIL", "Email"],
  ["SMS", "SMS"],
  ["PHONE_CALL", "Phone call"],
  ["POST", "Post"],
  ["IN_PERSON", "In person"],
  ["OTHER", "Other"],
] as const;

const today = () => new Date().toISOString().slice(0, 10);

/** What we actually know about whether the notice arrived, replies, postal dispatch, and the evidence pack. */
export default function DeliveryCard({ caseId, workflowState, onChanged }: { caseId: string; workflowState: string; onChanged: () => Promise<void> }) {
  const canPost = useCan("send_mail");
  const q = useQuery<DeliveryInfo>({
    queryKey: ["notice-delivery", caseId],
    queryFn: () => apiGet<DeliveryInfo>(`/recovery/cases/${caseId}/notice/delivery`),
  });
  const refresh = async () => {
    await onChanged();
    await q.refetch();
  };

  const [direction, setDirection] = useState<"IN" | "OUT">("IN");
  const [channel, setChannel] = useState<string>("WHATSAPP");
  const [when, setWhen] = useState(today());
  const [summary, setSummary] = useState("");
  const [isResponse, setIsResponse] = useState(true);
  const addCorr = useMutation({
    mutationFn: () =>
      apiPost(`/recovery/cases/${caseId}/correspondence`, { direction, channel, occurred_on: when, summary, is_response: direction === "IN" && isResponse }),
    onSuccess: async () => {
      setSummary("");
      await refresh();
      toast.success("Saved to the record");
    },
    onError: (e) => toast.error(describe(e)),
  });

  const [service, setService] = useState("Speed Post");
  const [tracking, setTracking] = useState("");
  const [sentOn, setSentOn] = useState(today());
  const addPostal = useMutation({
    mutationFn: () => apiPost(`/recovery/cases/${caseId}/notice/postal`, { service, tracking_no: tracking, sent_on: sentOn }),
    onSuccess: async () => {
      setTracking("");
      await refresh();
      toast.success("Recorded that the notice was posted");
    },
    onError: (e) => toast.error(describe(e)),
  });
  const [upd, setUpd] = useState<Record<string, string>>({});
  const addUpdate = useMutation({
    mutationFn: (pid: string) => apiPost(`/recovery/cases/${caseId}/notice/postal/${pid}/update`, { status: upd[pid] ?? "", date: today() }),
    onSuccess: async (_d, pid) => {
      setUpd({ ...upd, [pid]: "" });
      await refresh();
    },
    onError: (e) => toast.error(describe(e)),
  });

  const d = q.data;
  if (!d) return null;
  const postable = canPost && ["APPROVED", "SENT", "RESPONSE_RECEIVED"].includes(workflowState);

  return (
    <div className="mt-4 rounded-md border border-border p-4" data-testid="delivery-card">
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-sm">Delivery and replies</p>
        <Badge variant="outline" style={{ color: d.display_status === "Bounced" ? "#E5646E" : "#5B8CFF" }} data-testid="delivery-status">
          {d.display_status}
        </Badge>
      </div>

      <div className="mt-3 space-y-1.5 text-xs">
        {d.evidence.what_we_have.length === 0 && <p className="text-muted-foreground">Nothing has been sent yet.</p>}
        {d.evidence.what_we_have.map((x, i) => (
          <p key={i}>• {x}</p>
        ))}
        {d.evidence.what_we_have.length > 0 &&
          d.evidence.not_confirmed.map((x, i) => (
            <p key={i} className="text-muted-foreground" style={{ color: "#F0A63A" }}>
              ? {x}
            </p>
          ))}
      </div>

      {d.emails.some((e) => e.events.length > 0) && (
        <ul className="mt-2 space-y-0.5 text-xs text-muted-foreground">
          {d.emails.flatMap((e) => e.events.map((ev, i) => <li key={`${e.id}-${i}`}>{formatDateTime(ev.at)} · provider event: {ev.type.toLowerCase()}</li>))}
        </ul>
      )}

      {d.postal.map((p) => (
        <div key={p.id} className="mt-3 rounded-md border border-border p-2 text-xs" data-testid="postal-row">
          <p>
            {p.service} · tracking {p.tracking_no || "none"} · posted {formatDate(p.sent_on)} (version {p.version})
          </p>
          {p.updates.map((u, i) => (
            <p key={i} className="text-muted-foreground">
              {formatDate(u.date)} · {u.status}
            </p>
          ))}
          {canPost && (
            <div className="mt-1 flex gap-2">
              <Input className="h-7" placeholder="Tracking update, in your words (for example: Delivered, signed by R. Kumar)" value={upd[p.id] ?? ""} onChange={(e) => setUpd({ ...upd, [p.id]: e.target.value })} maxLength={200} />
              <Button size="xs" variant="outline" disabled={(upd[p.id] ?? "").trim().length < 2 || addUpdate.isPending} onClick={() => addUpdate.mutate(p.id)}>
                Add update
              </Button>
            </div>
          )}
        </div>
      ))}

      {postable && (
        <details className="mt-3 rounded-md border border-border p-3">
          <summary className="cursor-pointer text-xs">I posted the approved notice (Speed Post, registered post, courier)</summary>
          <div className="mt-2 grid gap-2 md:grid-cols-3">
            <Input value={service} onChange={(e) => setService(e.target.value)} placeholder="Service" maxLength={80} />
            <Input value={tracking} onChange={(e) => setTracking(e.target.value)} placeholder="Tracking number" maxLength={60} />
            <Input type="date" value={sentOn} max={today()} onChange={(e) => setSentOn(e.target.value)} />
          </div>
          <Button size="sm" variant="outline" className="mt-2" disabled={addPostal.isPending || service.trim().length < 2} onClick={() => addPostal.mutate()} data-testid="add-postal">
            Record posting
          </Button>
          <p className="mt-1 text-xs text-muted-foreground">VIDHI does not track parcels. Add each tracking update yourself from the courier&apos;s site.</p>
        </details>
      )}

      <details className="mt-3 rounded-md border border-border p-3" open={d.correspondence.length > 0}>
        <summary className="cursor-pointer text-xs">Replies and other messages with the customer ({d.correspondence.length})</summary>
        <ul className="mt-2 space-y-1 text-xs">
          {d.correspondence.map((x) => (
            <li key={x.id} className="border-l-2 pl-2" style={{ borderColor: "#C8A96B" }}>
              <span className="text-muted-foreground">
                {formatDate(x.occurred_on)} · {x.direction === "IN" ? "from the customer" : "from you"} · {x.channel.replace("_", " ").toLowerCase()}
                {x.is_response ? " · reply to the notice" : ""}
              </span>
              <p>{x.summary}</p>
            </li>
          ))}
        </ul>
        <div className="mt-3 grid gap-2 md:grid-cols-3">
          <select className="h-8 rounded-md border border-border bg-background px-2 text-sm" value={direction} onChange={(e) => setDirection(e.target.value as "IN" | "OUT")}>
            <option value="IN">From the customer</option>
            <option value="OUT">From me</option>
          </select>
          <select className="h-8 rounded-md border border-border bg-background px-2 text-sm" value={channel} onChange={(e) => setChannel(e.target.value)}>
            {CHANNELS.map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
          <Input type="date" value={when} max={today()} onChange={(e) => setWhen(e.target.value)} />
        </div>
        <Textarea className="mt-2" rows={2} placeholder="What was said or sent? (upload the message itself as proof, labelled “Messages or emails”)" value={summary} onChange={(e) => setSummary(e.target.value)} maxLength={2000} />
        {direction === "IN" && (
          <label className="mt-2 flex items-center gap-2 text-xs">
            <input type="checkbox" checked={isResponse} onChange={(e) => setIsResponse(e.target.checked)} /> This is the customer&apos;s reply to the notice
          </label>
        )}
        <Button size="sm" variant="outline" className="mt-2" disabled={summary.trim().length < 3 || addCorr.isPending} onClick={() => addCorr.mutate()} data-testid="add-correspondence">
          Add to the record
        </Button>
      </details>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <a {...fileLinkProps(`/api/recovery/cases/${caseId}/evidence-pack.zip`)}>
          <Button size="sm" variant="outline" data-testid="evidence-pack">
            Download the evidence pack
          </Button>
        </a>
        <span className="text-xs text-muted-foreground">Every version, approval, delivery record, reply and original file in one zip for you or your advocate.</span>
      </div>
    </div>
  );
}
