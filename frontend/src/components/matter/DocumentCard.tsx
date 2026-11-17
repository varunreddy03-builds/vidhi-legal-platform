import { lazy, Suspense, useEffect, useState } from "react";
import { openApiFile } from "@/lib/files";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { apiPatch } from "@/lib/api";
import { describe } from "@/lib/interaction";
import { useCan, useEntitlement } from "@/lib/useMe";
import type { DocumentAnalysis, DocumentOut } from "@/lib/types";
import AnalysisView from "./AnalysisView";
import ScanNotice from "./ScanNotice";

const PdfReader = lazy(() => import("./PdfReader"));
const DocxEditor = lazy(() => import("./DocxEditor"));

const DOC_CLASS_LABEL: Record<string, string> = {
  CONTRACT: "Contract",
  CHAT: "Chat / messages",
  BANK_STATEMENT: "Bank statement",
  FIR_POLICE: "Police record / FIR",
  FORENSIC_REPORT: "Forensic report",
  MEDICAL: "Medical record",
  CCTV_LOG: "CCTV / camera",
  COURT_ORDER: "Court record",
  LETTER: "Letter",
  MEDIA: "Photo / recording",
  OTHER: "Other",
};

const MEDIA_LABEL: Record<string, string> = { IMAGE: "Image", VIDEO: "Video", AUDIO: "Audio" };

export default function DocumentCard({
  d,
  analysis,
  analyzing,
  onAnalyze,
  onChanged,
}: {
  d: DocumentOut;
  analysis?: DocumentAnalysis;
  analyzing: boolean;
  onAnalyze: () => void;
  onChanged: () => Promise<void>;
}) {
  const [desc, setDesc] = useState(d.description ?? "");
  const [reading, setReading] = useState(false);
  const [editing, setEditing] = useState(false);
  const canWrite = useCan("write");
  useEffect(() => setDesc(d.description ?? ""), [d.description]);

  const patch = useMutation({
    mutationFn: (body: { doc_class?: string; description?: string }) => apiPatch<DocumentOut>(`/documents/${d.id}`, body),
    onSuccess: async () => {
      await onChanged();
      toast.success("Saved");
    },
    onError: (e) => toast.error(describe(e)),
  });

  const { data: ent } = useEntitlement();
  const isFree = ent?.plan === "FREE";
  const canAnalyze = d.processing_status === "READY" && d.text_available;
  const isMedia = d.media_kind !== "TEXT";

  return (
    <div className="glass rounded-lg p-4" data-testid="document-row">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-sm">{d.filename}</p>
          <p className="text-xs text-muted-foreground">
            {isMedia ? `${MEDIA_LABEL[d.media_kind]} evidence` : `${d.page_count} pages`}
            {d.text_available ? ` · ${d.citations.length} citations found · ${d.dates.length} dates found` : isMedia ? " · no text to read" : ""}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={d.processing_status === "READY" ? "secondary" : "destructive"}>{d.processing_status}</Badge>
          <select
            value={d.doc_class}
            onChange={(e) => patch.mutate({ doc_class: e.target.value })}
            aria-label="What kind of document is this?"
            className="h-7 rounded-lg border border-input bg-transparent px-2 text-xs outline-none focus-visible:border-ring dark:bg-input/30"
            data-testid="document-class-select"
          >
            {Object.entries(DOC_CLASS_LABEL).map(([k, v]) => (
              <option key={k} value={k} className="bg-popover">
                {v}
              </option>
            ))}
          </select>
          <Button size="xs" variant="outline" disabled={!canAnalyze || analyzing} onClick={onAnalyze} data-testid="analyze-document-button">
            {analyzing ? "Analysing…" : d.doc_class === "CONTRACT" ? (isFree ? "Summarise & flag risk · Pro" : "Summarise & flag risk") : "Analyse this evidence"}
          </Button>
          {d.has_file && d.document_type === "PDF" && (
            <Button size="xs" variant="outline" onClick={() => setReading(true)} data-testid="read-pdf">
              Read here
            </Button>
          )}
          {d.has_file && d.document_type === "DOCX" && canWrite && (
            <Button size="xs" variant="outline" onClick={() => setEditing(true)} data-testid="edit-docx">
              Edit text
            </Button>
          )}
          {d.has_file && (
            <Button size="xs" variant="ghost" onClick={() => openApiFile(`/api/documents/${d.id}/file`)} data-testid="download-original">
              Download original
            </Button>
          )}
        </div>
      </div>
      {d.doc_class_source === "AUTO" && d.doc_class !== "OTHER" && (
        <p className="mt-1 text-xs text-muted-foreground">Type detected automatically — change it if it is wrong.</p>
      )}
      {d.failure_reason && (
        <p className="mt-2 text-xs" style={{ color: "#F0A63A" }}>
          {d.failure_reason}
        </p>
      )}
      <ScanNotice d={d} />

      {isMedia && (
        <div className="mt-3" data-testid="media-description">
          <p className="text-xs text-muted-foreground">
            {d.text_available
              ? "Text read from the image is above. You can also describe what it shows:"
              : "VIDHI cannot watch or listen to this file. Describe what it shows so it is part of the matter (the research reads your description):"}
          </p>
          <Textarea
            rows={2}
            value={desc}
            onChange={(e) => setDesc(e.target.value)}
            maxLength={2000}
            className="mt-1 text-xs"
            data-testid="media-description-input"
          />
          <Button
            size="xs"
            variant="outline"
            className="mt-1.5"
            disabled={patch.isPending || desc === (d.description ?? "")}
            onClick={() => patch.mutate({ description: desc })}
            data-testid="media-description-save"
          >
            Save description
          </Button>
        </div>
      )}

      {analysis && <AnalysisView a={analysis} />}
      {editing && (<Suspense fallback={null}><DocxEditor docId={d.id} matterId={d.matter_id} title={d.filename} open={editing} onClose={() => setEditing(false)} /></Suspense>)}
      {reading && (<Suspense fallback={null}><PdfReader docId={d.id} title={d.filename} open={reading} onClose={() => setReading(false)} /></Suspense>)}
    </div>
  );
}
