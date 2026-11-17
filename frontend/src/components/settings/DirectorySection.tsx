import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { apiDelete, apiGet, apiPatch, apiPut } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { describe } from "@/lib/interaction";

interface Profile { display_name: string; city: string; state: string; practice_areas: string[]; languages: string[]; bio: string; enrolment_claim: string; listed: boolean; accepting_requests: boolean }
interface Mine { profile: Profile | null; directory_enabled: boolean; practice_areas: string[]; languages: string[]; notice: string }
interface Req { id: string; name: string; email: string; phone: string; message: string; status: string; at: string }
const EMPTY: Profile = { display_name: "", city: "", state: "", practice_areas: [], languages: ["en"], bio: "", enrolment_claim: "", listed: false, accepting_requests: true };
const STATUS = ["NEW", "CONTACTED", "DECLINED", "ARCHIVED"];

/** For lawyers: list yourself in the public directory (opt-in) and read consultation requests. Only active once the operator switches the directory on. */
export default function DirectorySection() {
  const qc = useQueryClient();
  const mine = useQuery({ queryKey: ["dir-mine"], queryFn: () => apiGet<Mine>("/directory/profile") });
  const reqs = useQuery({ queryKey: ["dir-requests"], queryFn: () => apiGet<Req[]>("/directory/requests") });
  const [p, setP] = useState<Profile>(EMPTY);
  useEffect(() => { if (mine.data) setP(mine.data.profile ?? EMPTY); }, [mine.data]);
  const save = useMutation({
    mutationFn: () => apiPut("/directory/profile", { ...p }),
    onSuccess: () => { toast.success("Saved."); void qc.invalidateQueries({ queryKey: ["dir-mine"] }); },
    onError: (e) => toast.error(describe(e)),
  });
  const setStatus = useMutation({ mutationFn: (v: { id: string; status: string }) => apiPatch(`/directory/requests/${v.id}`, { status: v.status }), onSuccess: () => void qc.invalidateQueries({ queryKey: ["dir-requests"] }), onError: (e) => toast.error(describe(e)) });
  const del = useMutation({ mutationFn: (id: string) => apiDelete(`/directory/requests/${id}`), onSuccess: () => void qc.invalidateQueries({ queryKey: ["dir-requests"] }), onError: (e) => toast.error(describe(e)) });
  const toggle = (list: string[], v: string) => (list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);

  return (
    <section className="glass rounded-lg p-5" data-testid="settings-directory">
      <h2 className="font-heading text-sm uppercase tracking-wider text-muted-foreground">Lawyer directory</h2>
      <p className="mt-2 text-sm text-muted-foreground">{mine.data?.notice}</p>
      {mine.data && !mine.data.directory_enabled && (
        <p className="mt-2 rounded-md border border-amber-500/40 bg-amber-500/10 p-2 text-sm" role="note">The public directory is switched off on this installation, so nothing you save here is visible to anyone yet.</p>
      )}
      <form className="mt-4 space-y-3" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-1.5"><Label htmlFor="d-name">Name shown</Label><Input id="d-name" value={p.display_name} onChange={(e) => setP({ ...p, display_name: e.target.value })} required minLength={2} maxLength={100} /></div>
          <div className="space-y-1.5"><Label htmlFor="d-enrol">Enrolment number (as you state it; not verified)</Label><Input id="d-enrol" value={p.enrolment_claim} onChange={(e) => setP({ ...p, enrolment_claim: e.target.value })} maxLength={40} /></div>
          <div className="space-y-1.5"><Label htmlFor="d-city">City</Label><Input id="d-city" value={p.city} onChange={(e) => setP({ ...p, city: e.target.value })} maxLength={60} /></div>
          <div className="space-y-1.5"><Label htmlFor="d-state">State</Label><Input id="d-state" value={p.state} onChange={(e) => setP({ ...p, state: e.target.value })} maxLength={60} /></div>
        </div>
        <fieldset className="space-y-1"><legend className="text-sm font-medium">Areas of practice</legend>
          <div className="flex flex-wrap gap-x-4 gap-y-1">{mine.data?.practice_areas.map((a) => <label key={a} className="flex items-center gap-1.5 text-sm"><input type="checkbox" checked={p.practice_areas.includes(a)} onChange={() => setP({ ...p, practice_areas: toggle(p.practice_areas, a) })} />{a}</label>)}</div></fieldset>
        <div className="space-y-1.5"><Label htmlFor="d-bio">Short bio (shown publicly)</Label><Textarea id="d-bio" rows={3} maxLength={800} value={p.bio} onChange={(e) => setP({ ...p, bio: e.target.value })} /></div>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={p.accepting_requests} onChange={(e) => setP({ ...p, accepting_requests: e.target.checked })} />Accept consultation requests</label>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={p.listed} onChange={(e) => setP({ ...p, listed: e.target.checked })} data-testid="directory-listed" />List me in the public directory (you can stop at any time)</label>
        <Button type="submit" loading={save.isPending}>Save</Button>
      </form>

      <h3 className="mt-6 text-lg">Consultation requests</h3>
      <div className="mt-2 space-y-3" data-testid="directory-requests">
        {(reqs.data ?? []).map((r) => (
          <div key={r.id} className="rounded-md border border-border p-3 text-sm">
            <p><strong>{r.name}</strong> · {r.email}{r.phone ? ` · ${r.phone}` : ""} <span className="text-xs text-muted-foreground">(contact details not verified)</span></p>
            <p className="mt-1 whitespace-pre-wrap">{r.message}</p>
            <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <span>{formatDateTime(r.at)}</span>
              <select className="h-7 rounded-md border border-border bg-background px-2" value={r.status} onChange={(e) => setStatus.mutate({ id: r.id, status: e.target.value })} aria-label="Status">{STATUS.map((s) => <option key={s}>{s}</option>)}</select>
              <button className="underline" onClick={() => { if (window.confirm("Delete this request?")) del.mutate(r.id); }}>Delete</button>
            </div>
          </div>
        ))}
        {reqs.isSuccess && reqs.data.length === 0 && <p className="text-sm text-muted-foreground">No requests yet.</p>}
      </div>
    </section>
  );
}