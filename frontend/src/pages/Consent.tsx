import { useState } from "react";
import { useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import NervousSystemBackground from "@/components/NervousSystemBackground";
import { Button } from "@/components/ui/button";
import { apiGet, apiPost } from "@/lib/api";
import { describe } from "@/lib/interaction";
import type { ConsentInfo } from "@/lib/types";

/** Public page (no login): an accountant agrees to - or stops - being copied on statements. */
export default function Consent() {
  const { token = "" } = useParams();
  const qc = useQueryClient();
  const [error, setError] = useState("");

  const info = useQuery<ConsentInfo>({
    queryKey: ["consent", token],
    queryFn: () => apiGet<ConsentInfo>(`/public/consent/${token}`),
    retry: false,
  });

  const act = useMutation({
    mutationFn: (action: "confirm" | "decline") => apiPost(`/public/consent/${token}`, { action }),
    onSuccess: async () => {
      setError("");
      await qc.invalidateQueries({ queryKey: ["consent", token] });
    },
    onError: (e) => setError(describe(e)),
  });

  const i = info.data;
  return (
    <main id="main-content" className="relative flex min-h-screen items-center justify-center px-4">
      <NervousSystemBackground intensity="ambient" />
      <div className="glass relative z-10 w-full max-w-md rounded-xl p-8" data-testid="consent-page">
        <p className="font-heading text-xs tracking-[0.3em] text-muted-foreground">◈ VIDHI</p>
        {info.isLoading && <h1 className="mt-4 text-xl">Loading…</h1>}
        {info.isError && (
          <>
            <h1 className="mt-4 text-xl">This link is not valid</h1>
            <p className="mt-2 text-sm text-muted-foreground">It may be incomplete or no longer active.</p>
          </>
        )}
        {i && (
          <>
            <h1 className="mt-4 text-xl">Copy on payment statements?</h1>
            <p className="mt-2 text-sm text-muted-foreground">
              {i.owner_name || "Someone"}
              {i.owner_email ? ` (${i.owner_email})` : ""} asked to copy <strong>{i.email}</strong> on statements about
              money owed to {i.creditor_name}, sent through VIDHI.
            </p>

            {i.status === "CONFIRMED" && (
              <>
                <p className="mt-4 text-sm" style={{ color: "#5B8CFF" }} data-testid="consent-confirmed">
                  You are receiving these copies. You can stop at any time.
                </p>
                <Button className="mt-3" variant="outline" onClick={() => act.mutate("decline")} disabled={act.isPending} data-testid="consent-stop">
                  Stop receiving them
                </Button>
              </>
            )}
            {i.status === "DECLINED" && (
              <p className="mt-4 text-sm" data-testid="consent-declined">
                You will not receive any copies. Nothing more is needed.
              </p>
            )}
            {i.status === "BOUNCED" && <p className="mt-4 text-sm">This address could not be reached.</p>}
            {i.status === "PENDING" && i.expired && (
              <p className="mt-4 text-sm" style={{ color: "#F0A63A" }}>
                This request has expired. If you still want the copies, ask the sender to send it again.
              </p>
            )}
            {i.status === "PENDING" && i.can_confirm && (
              <div className="mt-5 flex flex-wrap gap-2">
                <Button onClick={() => act.mutate("confirm")} disabled={act.isPending} data-testid="consent-confirm">
                  Yes, copy me
                </Button>
                <Button variant="outline" onClick={() => act.mutate("decline")} disabled={act.isPending} data-testid="consent-decline">
                  No thanks
                </Button>
              </div>
            )}
            {error && (
              <p className="mt-3 text-sm" style={{ color: "#E0604D" }} role="alert">
                {error}
              </p>
            )}
          </>
        )}
      </div>
    </main>
  );
}
