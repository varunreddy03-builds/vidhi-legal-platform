import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { apiDelete, apiFetch, apiGet, apiPost } from "@/lib/api";
import { describe } from "@/lib/interaction";
import { useCan } from "@/lib/useMe";
import { Textarea } from "@/components/ui/textarea";
import type { PDFDocumentProxy } from "pdfjs-dist";
import "pdfjs-dist/web/pdf_viewer.css";

type Box = { x: number; y: number; w: number; h: number };
type Marks = number[];
type Note = { id: string; page: number; note: string; quote: string; author: string; created_at: string };

const STORE = "vidhi-pdf-bookmarks";

function readMarks(docId: string): Marks {
  try {
    const all = JSON.parse(localStorage.getItem(STORE) ?? "{}") as Record<string, Marks>;
    return Array.isArray(all[docId]) ? all[docId].filter((n) => Number.isInteger(n)) : [];
  } catch {
    return [];
  }
}

function writeMarks(docId: string, marks: Marks) {
  try {
    const all = JSON.parse(localStorage.getItem(STORE) ?? "{}") as Record<string, Marks>;
    all[docId] = marks;
    localStorage.setItem(STORE, JSON.stringify(all));
  } catch {
    /* private window or blocked storage: bookmarks simply do not persist */
  }
}

/** Reads one PDF from the matter inside the page: page by page, with zoom, search and yellow marks on the words found, and bookmarks kept on this device.
 * The file is fetched with the person's own session and never leaves the browser. pdf.js is loaded only when this opens. */
export default function PdfReader({ docId, title, open, onClose }: { docId: string; title: string; open: boolean; onClose: () => void }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const textLayer = useRef<HTMLDivElement>(null);
  const [saved, setSaved] = useState<Box[]>([]); // passages the firm's notes on this page are about
  const [pdf, setPdf] = useState<PDFDocumentProxy | null>(null);
  const [page, setPage] = useState(1);
  const [zoom, setZoom] = useState(1.2);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<number[]>([]); // pages that contain the search words
  const [boxes, setBoxes] = useState<Box[]>([]);
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [marks, setMarks] = useState<Marks>(() => readMarks(docId));
  const [jump, setJump] = useState("1");
  const qc = useQueryClient();
  const canWrite = useCan("write");
  const [draft, setDraft] = useState("");
  const [quote, setQuote] = useState("");
  const notes = useQuery({ queryKey: ["doc-notes", docId], queryFn: () => apiGet<Note[]>(`/documents/${docId}/notes`), enabled: open });
  const addNote = useMutation({
    mutationFn: () => apiPost<Note>(`/documents/${docId}/notes`, { page, note: draft, quote }),
    onSuccess: async () => {
      setDraft("");
      setQuote("");
      await qc.invalidateQueries({ queryKey: ["doc-notes", docId] });
      toast.success("Note saved");
    },
    onError: (e) => toast.error(describe(e)),
  });
  const notesRef = useRef<Note[] | undefined>(undefined);
  notesRef.current = notes.data;
  const delNote = useMutation({
    mutationFn: (id: string) => apiDelete(`/documents/${docId}/notes/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["doc-notes", docId] }),
    onError: (e) => toast.error(describe(e)),
  });

  useEffect(() => {
    if (!open) return;
    let dead = false;
    let doc: PDFDocumentProxy | null = null;
    setLoading(true);
    setError("");
    setPdf(null);
    setPage(1);
    setJump("1");
    setQuery("");
    setHits([]);
    setMarks(readMarks(docId));
    (async () => {
      try {
        const res = await apiFetch(`/api/documents/${docId}/file`);
        if (!res.ok) throw new Error(String(res.status));
        const data = new Uint8Array(await res.arrayBuffer());
        const pdfjs = await import("pdfjs-dist");
        const worker = (await import("pdfjs-dist/build/pdf.worker.min.mjs?url")).default;
        pdfjs.GlobalWorkerOptions.workerSrc = worker;
        doc = await pdfjs.getDocument({ data, isEvalSupported: false }).promise;
        if (dead) {
          void doc.destroy();
          return;
        }
        setPdf(doc);
      } catch {
        if (!dead) setError("This file could not be opened here. Use Download original instead.");
      } finally {
        if (!dead) setLoading(false);
      }
    })();
    return () => {
      dead = true;
      if (doc) void doc.destroy();
    };
  }, [open, docId]);

  const words = useMemo(() => query.trim().toLowerCase(), [query]);

  // draw the current page, and find the marks for the search words on it
  useEffect(() => {
    if (!pdf || !canvas.current) return;
    let dead = false;
    let task: { cancel: () => void } | null = null;
    (async () => {
      const p = await pdf.getPage(page);
      const viewport = p.getViewport({ scale: zoom });
      const el = canvas.current;
      if (!el || dead) return;
      el.width = Math.floor(viewport.width);
      el.height = Math.floor(viewport.height);
      setSize({ w: el.width, h: el.height });
      const ctx = el.getContext("2d");
      if (!ctx) return;
      const render = p.render({ canvasContext: ctx, viewport });
      task = render;
      try {
        await render.promise;
      } catch {
        return; // cancelled by a newer draw
      }
      if (dead) return;
      const text = await p.getTextContent();
      // selectable (transparent) text over the picture, so a passage can be picked for a note
      const layer = textLayer.current;
      if (layer) {
        layer.replaceChildren();
        const pdfjs = await import("pdfjs-dist");
        if (dead) return;
        try {
          await new pdfjs.TextLayer({ textContentSource: text, container: layer, viewport }).render();
        } catch {
          /* no text layer: the page still reads, it just cannot be selected */
        }
      }
      // blue marks on the passages that this page's saved notes are about
      const norm = (v: string) => v.replace(/\s+/g, " ").trim().toLowerCase();
      const quotes = (notesRef.current ?? []).filter((n) => n.page === page && norm(n.quote).length >= 3).map((n) => norm(n.quote));
      const place = (item: { transform: number[]; height: number; width: number }): Box => {
        const t = viewport.transform;
        const m = item.transform;
        const h = Math.abs(item.height * zoom) || 12;
        return { x: t[0] * m[4] + t[2] * m[5] + t[4], y: t[1] * m[4] + t[3] * m[5] + t[5] - h, w: item.width * zoom, h: h * 1.15 };
      };
      const keep: Box[] = [];
      for (const item of text.items) {
        if (!("str" in item)) continue;
        const s = norm(item.str);
        if (s.length >= 3 && quotes.some((q) => s.includes(q) || q.includes(s))) keep.push(place(item));
      }
      if (!dead) setSaved(keep);
      if (!words) {
        setBoxes([]);
        return;
      }
      const found: Box[] = [];
      for (const item of text.items) {
        if (!("str" in item) || !item.str.toLowerCase().includes(words)) continue;
        const t = viewport.transform;
        const m = item.transform;
        const x = t[0] * m[4] + t[2] * m[5] + t[4];
        const y = t[1] * m[4] + t[3] * m[5] + t[5];
        const h = Math.abs(item.height * zoom) || 12;
        found.push({ x, y: y - h, w: item.width * zoom, h: h * 1.15 });
      }
      if (!dead) setBoxes(found);
    })().catch(() => undefined);
    return () => {
      dead = true;
      task?.cancel();
    };
  }, [pdf, page, zoom, words, notes.data]);

  // which pages hold the search words (after a short pause in typing)
  useEffect(() => {
    if (!pdf || !words) {
      setHits([]);
      return;
    }
    let dead = false;
    const timer = setTimeout(async () => {
      const found: number[] = [];
      for (let n = 1; n <= pdf.numPages && !dead; n++) {
        const t = await (await pdf.getPage(n)).getTextContent();
        if (t.items.some((i) => "str" in i && i.str.toLowerCase().includes(words))) found.push(n);
      }
      if (!dead) setHits(found);
    }, 300);
    return () => {
      dead = true;
      clearTimeout(timer);
    };
  }, [pdf, words]);

  const total = pdf?.numPages ?? 0;
  const go = useCallback((n: number) => {
    if (!total) return;
    const next = Math.min(Math.max(1, Math.round(n)), total);
    setPage(next);
    setJump(String(next));
  }, [total]);
  const nextHit = (dir: 1 | -1) => {
    if (!hits.length) return;
    const ordered = dir === 1 ? hits.filter((h) => h > page) : hits.filter((h) => h < page).reverse();
    go(ordered[0] ?? (dir === 1 ? hits[0] : hits[hits.length - 1]));
  };
  const useSelection = () => {
    const sel = window.getSelection();
    const text = sel && textLayer.current && sel.anchorNode && textLayer.current.contains(sel.anchorNode) ? sel.toString().replace(/\s+/g, " ").trim() : "";
    if (text) setQuote(text.slice(0, 500));
    else toast.message("Select some text on the page first");
  };
  const marked = marks.includes(page);
  const toggleMark = () => {
    const next = marked ? marks.filter((m) => m !== page) : [...marks, page].sort((a, b) => a - b);
    setMarks(next);
    writeMarks(docId, next);
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[92vh] w-[min(96vw,60rem)] max-w-none overflow-hidden sm:max-w-none" data-testid="pdf-reader">
        <DialogHeader>
          <DialogTitle className="truncate">{title}</DialogTitle>
          <DialogDescription>Reading copy. The original file is unchanged. Search, bookmarks and zoom stay on this device.</DialogDescription>
        </DialogHeader>
        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
        {loading && <p className="text-sm text-muted-foreground">Opening…</p>}
        {pdf && (
          <>
            <div className="flex flex-wrap items-center gap-2" role="toolbar" aria-label="PDF reader controls">
              <Button size="xs" variant="outline" onClick={() => go(page - 1)} disabled={page <= 1} aria-label="Previous page">‹</Button>
              <label className="flex items-center gap-1 text-xs">
                Page
                <Input
                  value={jump}
                  inputMode="numeric"
                  aria-label="Go to page"
                  className="h-7 w-14 text-center"
                  onChange={(e) => setJump(e.target.value.replace(/\D/g, ""))}
                  onKeyDown={(e) => e.key === "Enter" && go(Number(jump) || 1)}
                />
                of {total}
              </label>
              <Button size="xs" variant="outline" onClick={() => go(page + 1)} disabled={page >= total} aria-label="Next page">›</Button>
              <Button size="xs" variant="outline" onClick={() => setZoom((z) => Math.max(0.6, +(z - 0.2).toFixed(1)))} aria-label="Zoom out">−</Button>
              <Button size="xs" variant="outline" onClick={() => setZoom((z) => Math.min(3, +(z + 0.2).toFixed(1)))} aria-label="Zoom in">+</Button>
              <Button size="xs" variant={marked ? "secondary" : "outline"} onClick={toggleMark} aria-pressed={marked} data-testid="pdf-bookmark">
                {marked ? "Bookmarked" : "Bookmark page"}
              </Button>
              <Input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search this PDF"
                aria-label="Search this PDF"
                className="h-7 w-44"
                data-testid="pdf-search"
              />
              <Button size="xs" variant="outline" onClick={() => nextHit(-1)} disabled={!hits.length} aria-label="Previous match">↑</Button>
              <Button size="xs" variant="outline" onClick={() => nextHit(1)} disabled={!hits.length} aria-label="Next match">↓</Button>
              <span className="text-xs text-muted-foreground" aria-live="polite" data-testid="pdf-hits">
                {words ? (hits.length ? `Found on ${hits.length} page${hits.length === 1 ? "" : "s"}: ${hits.slice(0, 12).join(", ")}${hits.length > 12 ? "…" : ""}` : "No match") : ""}
              </span>
            </div>
            {marks.length > 0 && (
              <p className="text-xs text-muted-foreground">
                Bookmarks:{" "}
                {marks.map((m) => (
                  <button key={m} type="button" className="mr-2 underline" onClick={() => go(m)}>
                    p. {m}
                  </button>
                ))}
              </p>
            )}
            <section aria-label={`Notes on page ${page}`} className="rounded-lg border p-2" data-testid="pdf-notes">
              <h4 className="text-xs font-medium">Notes on page {page}{notes.data && notes.data.length > 0 ? ` · ${notes.data.length} on this document (pages ${[...new Set(notes.data.map((n) => n.page))].join(", ")})` : ""}</h4>
              <ul className="mt-1 space-y-1 text-xs">
                {(notes.data ?? []).filter((n) => n.page === page).map((n) => (
                  <li key={n.id} className="rounded border p-1.5" data-testid="pdf-note">
                    {n.quote && <q className="block text-muted-foreground">{n.quote}</q>}
                    <span className="whitespace-pre-wrap">{n.note}</span>
                    <span className="block text-muted-foreground">{n.author}</span>
                    {canWrite && (
                      <button type="button" className="underline" onClick={() => delNote.mutate(n.id)} aria-label={`Delete note: ${n.note.slice(0, 40)}`}>
                        Delete note
                      </button>
                    )}
                  </li>
                ))}
              </ul>
              {canWrite && (
                <form
                  className="mt-2 space-y-1"
                  onSubmit={(e) => {
                    e.preventDefault();
                    if (draft.trim()) addNote.mutate();
                  }}
                >
                  <Button type="button" size="xs" variant="outline" data-testid="pdf-use-selection" onMouseDown={(e) => e.preventDefault()} onClick={useSelection}>
                    Use selected text
                  </Button>
                  <Input value={quote} onChange={(e) => setQuote(e.target.value)} maxLength={500} placeholder="Passage this is about (optional)" aria-label="Passage this note is about" className="h-7 text-xs" data-testid="pdf-note-quote" />
                  <Textarea value={draft} onChange={(e) => setDraft(e.target.value)} maxLength={2000} rows={2} placeholder="Add a note for your firm on this page" aria-label="Note for this page" className="text-xs" data-testid="pdf-note-text" />
                  <Button type="submit" size="xs" variant="outline" disabled={!draft.trim() || addNote.isPending} data-testid="pdf-note-add">
                    Save note
                  </Button>
                  <span className="ml-2 text-xs text-muted-foreground">Seen by your firm. Not sent to any AI.</span>
                </form>
              )}
            </section>
            <div className="max-h-[68vh] overflow-auto rounded-lg border bg-muted/30 p-2" tabIndex={0} role="region" aria-label="PDF page. Use the arrow keys to scroll.">
              <div className="relative mx-auto" style={{ width: size.w, height: size.h }}>
                <canvas ref={canvas} aria-label={`Page ${page} of ${total}`} role="img" />
                {saved.map((b, i) => (
                  <span key={`s${i}`} aria-hidden data-testid="pdf-saved-mark" className="pointer-events-none absolute rounded-sm" style={{ left: b.x, top: b.y, width: b.w, height: b.h, background: "rgba(59, 130, 246, 0.3)" }} />
                ))}
                {boxes.map((b, i) => (
                  <span key={i} aria-hidden data-testid="pdf-mark" className="pointer-events-none absolute rounded-sm" style={{ left: b.x, top: b.y, width: b.w, height: b.h, background: "rgba(255, 210, 0, 0.4)" }} />
                ))}
                <div ref={textLayer} className="textLayer" data-testid="pdf-text-layer" style={{ ["--scale-factor" as string]: zoom }} />
              </div>
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
