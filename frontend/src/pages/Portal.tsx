import { useEffect } from "react";
import { fileLinkProps } from "@/lib/files";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { ApiError, apiGet } from "@/lib/api";
import { endSession } from "@/lib/session";
import { formatDateTime } from "@/lib/format";
import { useMe } from "@/lib/useMe";
import { LanguageMenu, ThemeToggle } from "@/components/AppearanceControls";
import { LegalLinks } from "@/lib/legal";
import SharedGraph, { type SharedGraphData } from "@/components/SharedGraph";

interface Item { id: string; title: string; status: string; updates: number; documents: number }
interface Detail {
  firm: string;
  id: string;
  title: string;
  status: string;
  updates: { id: string; text: string; by: string; at: string }[];
  documents: { id: string; filename: string; shared_at: string }[];
  notice: string;
}

/** What a client of the firm sees: only what their lawyer shared, read-only. Deliberately not inside the firm's workspace layout. */
export default function Portal() {
  const { data: me, isLoading } = useMe();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const chosen = params.get("m");

  useEffect(() => {
    if (isLoading) return;
    if (me === null) navigate("/login?next=/portal", { replace: true });
    else if (me && me.role !== "CLIENT") navigate("/start", { replace: true }); // the firm's own people use the workspace
  }, [isLoading, me, navigate]);

  const list = useQuery({ queryKey: ["portal-matters"], queryFn: () => apiGet<{ firm: string; matters: Item[] }>("/portal/matters"), enabled: me?.role === "CLIENT" });
  const detail = useQuery({
    queryKey: ["portal-matter", chosen],
    queryFn: () => apiGet<Detail>(`/portal/matters/${chosen}`),
    enabled: me?.role === "CLIENT" && !!chosen,
    retry: (n, e) => !(e instanceof ApiError && e.status === 404) && n < 1,
  });

  const { data: graphData } = useQuery({ queryKey: ["portal-graph", chosen], queryFn: () => apiGet<{ graph: SharedGraphData | null }>(`/portal/matters/${chosen}/graph`), enabled: me?.role === "CLIENT" && !!chosen && !!detail.data });

  const out = async () => {
    await endSession();
    navigate("/login", { replace: true });
  };

  return (
    <main id="main-content" className="min-h-screen px-4 py-6" data-testid="portal-page">
      <div className="mx-auto max-w-3xl space-y-6">
        <header className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="font-heading text-xs tracking-[0.3em] text-muted-foreground">◈ VIDHI</p>
            <h1 className="mt-1 text-2xl">{list.data?.firm ?? me?.organization_name ?? "Client portal"}</h1>
            <p className="text-sm text-muted-foreground">Client portal for {me?.full_name}</p>
          </div>
          <div className="flex items-center gap-2">
            <LanguageMenu />
            <ThemeToggle />
            <Button variant="outline" size="sm" onClick={() => void out()} data-testid="portal-signout">Sign out</Button>
          </div>
        </header>
        <p className="text-sm text-muted-foreground">You see only what your lawyer chose to share with you. This page is read-only and is not legal advice.</p>

        {!chosen && (
          <div className="space-y-3" data-testid="portal-matters">
            {(list.data?.matters ?? []).map((m) => (
              <button key={m.id} className="glass block w-full rounded-lg p-4 text-left" onClick={() => setParams({ m: m.id })} data-testid="portal-matter-card">
                <p className="font-medium">{m.title}</p>
                <p className="text-sm text-muted-foreground">{m.status.replace("_", " ").toLowerCase()} · {m.updates} update(s) · {m.documents} document(s)</p>
              </button>
            ))}
            {list.isSuccess && list.data.matters.length === 0 && <p className="text-sm text-muted-foreground">Nothing has been shared with you yet.</p>}
          </div>
        )}

        {chosen && (
          <div className="space-y-5" data-testid="portal-matter">
            <Button variant="ghost" size="sm" onClick={() => setParams({})}>← All matters</Button>
            {detail.isError && <p className="text-sm">This matter is not available to you.</p>}
            {detail.data && (
              <>
                <div>
                  <h2 className="text-xl">{detail.data.title}</h2>
                  <p className="text-sm text-muted-foreground">Status: {detail.data.status.replace("_", " ").toLowerCase()}</p>
                </div>
                <section className="space-y-2">
                  <h3 className="text-lg">Updates from your lawyer</h3>
                  {detail.data.updates.length === 0 && <p className="text-sm text-muted-foreground">No updates yet.</p>}
                  {detail.data.updates.map((u) => (
                    <div key={u.id} className="glass rounded-lg p-3" data-testid="portal-update">
                      <p className="whitespace-pre-wrap text-sm">{u.text}</p>
                      <p className="mt-1 text-xs text-muted-foreground">{u.by} · {formatDateTime(u.at)}</p>
                    </div>
                  ))}
                </section>
                <section className="space-y-2">
                  <h3 className="text-lg">Documents shared with you</h3>
                  {detail.data.documents.length === 0 && <p className="text-sm text-muted-foreground">No documents shared yet.</p>}
                  {detail.data.documents.map((d) => (
                    <div key={d.id} className="glass flex items-center justify-between gap-2 rounded-lg p-3" data-testid="portal-document">
                      <span className="text-sm">{d.filename}</span>
                      <a className="text-sm underline underline-offset-4" {...fileLinkProps(`/api/portal/matters/${detail.data.id}/documents/${d.id}/file`, { download: false })}>Download</a>
                    </div>
                  ))}
                </section>
                {graphData?.graph && (
                  <section className="space-y-2" data-testid="portal-graph">
                    <h3 className="text-lg">How the documents connect</h3>
                    <SharedGraph graph={graphData.graph} testId="portal-graph-view" />
                  </section>
                )}
                <p className="text-xs text-muted-foreground">{detail.data.notice}</p>
              </>
            )}
          </div>
        )}
        <LegalLinks className="justify-center" />
        <p className="text-center text-xs text-muted-foreground">Need help? <Link to="/support" className="underline">Contact support</Link></p>
      </div>
    </main>
  );
}