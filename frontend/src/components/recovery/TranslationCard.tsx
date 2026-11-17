import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { apiGet, apiPatch, apiPost } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { describe } from "@/lib/interaction";
import type { NoticeTranslation, TranslationList } from "@/lib/types";
import { useCan } from "@/lib/useMe";

/** Courtesy translations: code keeps the figures and names intact; a person must read and approve before one is emailed. */
export default function TranslationCard({ caseId }: { caseId: string }) {
  const canAi = useCan("ai");
  const canApprove = useCan("send_mail");
  const q = useQuery<TranslationList>({
    queryKey: ["notice-translations", caseId],
    queryFn: () => apiGet<TranslationList>(`/recovery/cases/${caseId}/notice/translations`),
  });
  const [lang, setLang] = useState("hi");
  const [editId, setEditId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [ack, setAck] = useState<Record<string, boolean>>({});
  const refresh = () => q.refetch();

  const translate = useMutation({
    mutationFn: () => apiPost<NoticeTranslation>(`/recovery/cases/${caseId}/notice/translate`, { language: lang }),
    onSuccess: async () => {
      await refresh();
      toast.success("Translation ready. Have someone fluent read it before you approve it.");
    },
    onError: (e) => toast.error(describe(e)),
  });
  const save = useMutation({
    mutationFn: (id: string) => apiPatch<NoticeTranslation>(`/recovery/cases/${caseId}/notice/translations/${id}`, { body: draft }),
    onSuccess: async () => {
      setEditId(null);
      await refresh();
      toast.success("Saved. The checks were run again and any approval was cleared.");
    },
    onError: (e) => toast.error(describe(e)),
  });
  const approve = useMutation({
    mutationFn: (id: string) => apiPost(`/recovery/cases/${caseId}/notice/translations/${id}/approve`, { acknowledged: !!ack[id] }),
    onSuccess: async () => {
      await refresh();
      toast.success("Approved. You can include it when you email the notice.");
    },
    onError: (e) => toast.error(describe(e)),
  });

  const d = q.data;
  if (!d) return null;

  return (
    <div className="mt-4 rounded-md border border-border p-4" data-testid="translation-card">
      <p className="text-sm">Translation (optional)</p>
      <p className="mt-1 text-xs text-muted-foreground">
        If your customer reads another language, you can send a courtesy translation under the English notice. The English stays the notice
        that counts.
      </p>
      {canAi && (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <select className="h-8 rounded-md border border-border bg-background px-2 text-sm" value={lang} onChange={(e) => setLang(e.target.value)} data-testid="translation-language">
            {d.languages.map((l) => (
              <option key={l.code} value={l.code}>
                {l.name}
              </option>
            ))}
          </select>
          <Button size="sm" variant="outline" disabled={translate.isPending} onClick={() => translate.mutate()} data-testid="translate-button">
            {translate.isPending ? "Translating…" : "Translate the current notice"}
          </Button>
        </div>
      )}

      <div className="mt-3 space-y-3">
        {d.translations.map((t) => (
          <div key={t.id} className="rounded-md border border-border p-3 text-xs" data-testid="translation-row">
            <div className="flex flex-wrap items-center gap-2">
              <span>{t.language_name}</span>
              <span className="text-muted-foreground">{formatDateTime(t.created_at)}</span>
              {t.stale && <Badge variant="outline" style={{ color: "#F0A63A" }}>Out of date</Badge>}
              {t.usable && <Badge variant="outline" style={{ color: "#5B8CFF" }}>Approved</Badge>}
              {!t.checks.ok && <Badge variant="outline" style={{ color: "#E5646E" }}>Needs fixing</Badge>}
            </div>
            {t.stale && <p className="mt-1" style={{ color: "#F0A63A" }}>The English notice changed after this was made. Translate again.</p>}
            {t.checks.problems.map((p) => (
              <p key={p} className="mt-1" style={{ color: "#E5646E" }}>{p}</p>
            ))}
            {editId === t.id ? (
              <div className="mt-2">
                <Textarea rows={12} value={draft} onChange={(e) => setDraft(e.target.value)} maxLength={16000} className="text-xs" />
                <div className="mt-2 flex gap-2">
                  <Button size="xs" disabled={save.isPending || draft.trim().length < 20} onClick={() => save.mutate(t.id)}>Save</Button>
                  <Button size="xs" variant="outline" onClick={() => setEditId(null)}>Cancel</Button>
                </div>
              </div>
            ) : (
              <pre className="mt-2 max-h-56 overflow-auto whitespace-pre-wrap rounded border border-border bg-background/40 p-2">{t.body}</pre>
            )}
            {editId !== t.id && !t.stale && (
              <div className="mt-2 space-y-2">
                <Button size="xs" variant="ghost" onClick={() => { setDraft(t.body); setEditId(t.id); }}>Edit the wording</Button>
                {canApprove && !t.usable && t.checks.ok && (
                  <div>
                    <label className="flex items-start gap-2">
                      <input type="checkbox" className="mt-0.5" checked={!!ack[t.id]} onChange={(e) => setAck({ ...ack, [t.id]: e.target.checked })} />
                      <span>This translation was read by someone fluent in {t.language_name}, and I want it sent under the English notice.</span>
                    </label>
                    <Button size="xs" className="mt-1" disabled={!ack[t.id] || approve.isPending} onClick={() => approve.mutate(t.id)} data-testid="approve-translation">
                      Approve this translation
                    </Button>
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
      <ul className="mt-3 space-y-1 text-xs text-muted-foreground">
        {d.notes.map((n) => (
          <li key={n}>{n}</li>
        ))}
      </ul>
    </div>
  );
}
