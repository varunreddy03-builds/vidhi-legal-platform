import type { DocumentOut } from "@/lib/types";

const ENGINE: Record<string, string> = { tesseract: "Tesseract (a scan reader)", "hosted-vision": "an AI reader", "embedded-text": "the file's own text" };

/** Says, in plain words, that text read from a scan may contain mistakes, and which pages: so low-confidence text is never taken for the original. VIDHI also never calls a statement that
 * rests on such a page verified (the server decides that; this only tells the person). */
export default function ScanNotice({ d }: { d: Pick<DocumentOut, "reading_note" | "uncertain_pages" | "page_meta"> }) {
  const pages = d.uncertain_pages ?? [];
  if (pages.length === 0 && !d.reading_note) return null;
  const meta = new Map((d.page_meta ?? []).map((m) => [m.page, m]));
  return (
    <div className="mt-2 rounded-lg border px-3 py-2 text-xs" style={{ borderColor: "#F0A63A", color: "#F0A63A" }} role="note" data-testid="scan-notice">
      {pages.length > 0 && (
        <p data-testid="scan-uncertain">
          <strong>Read from a scan: check against the original.</strong> {pages.length === 1 ? "Page" : "Pages"} {pages.join(", ")} may contain mistakes (empty, low confidence or unreadable words). A statement
          that rests on {pages.length === 1 ? "it" : "them"} is never shown as verified.
        </p>
      )}
      {pages.length > 0 && (
        <ul className="mt-1 list-disc pl-4" data-testid="scan-pages">
          {pages.slice(0, 12).map((p) => {
            const m = meta.get(p);
            return (
              <li key={p}>
                Page {p}: {m ? `read by ${ENGINE[m.engine] ?? m.engine}` : "read from a scan"}
                {m && m.confidence != null ? `, the reader's own confidence ${Math.round(m.confidence)}%` : m ? ", the reader gave no confidence figure" : ""}
                {m && m.warnings?.length ? `. ${m.warnings[0]}` : ""}
              </li>
            );
          })}
          {pages.length > 12 && <li>and {pages.length - 12} more pages</li>}
        </ul>
      )}
      {d.reading_note && <p className={pages.length > 0 ? "mt-1" : ""} data-testid="scan-note">{d.reading_note}</p>}
    </div>
  );
}
