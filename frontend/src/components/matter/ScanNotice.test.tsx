import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import ScanNotice from "./ScanNotice";

const draw = (d: Parameters<typeof ScanNotice>[0]["d"]) => renderToStaticMarkup(<ScanNotice d={d} />);

describe("scan notice", () => {
  it("shows nothing for a document whose text is not in doubt", () => {
    expect(draw({ uncertain_pages: [], reading_note: null, page_meta: [] })).toBe("");
    expect(draw({})).toBe("");
  });

  it("marks uncertain pages, says to check the original and that nothing on them is shown as verified", () => {
    const html = draw({
      uncertain_pages: [2, 5],
      reading_note: "This text was read from a scan and may contain mistakes.",
      page_meta: [
        { page: 2, engine: "tesseract", confidence: 41.4, uncertain: true, warnings: [] },
        { page: 5, engine: "hosted-vision", confidence: null, uncertain: true, warnings: ["Read by an AI reader: no confidence figure."] },
      ],
    });
    expect(html).toContain('data-testid="scan-notice"');
    expect(html).toContain("Read from a scan: check against the original");
    expect(html).toContain("Pages 2, 5 may contain mistakes");
    expect(html).toContain("never shown as verified");
    expect(html).toContain("the reader&#x27;s own confidence 41%");
    expect(html).toContain("the reader gave no confidence figure"); // page 5 was read by an AI reader, which reports none: the notice says so instead of inventing a number
    expect(html).toContain("Read by an AI reader: no confidence figure.");
    expect(html).toContain("This text was read from a scan and may contain mistakes.");
  });

  it("uses the singular for one page and shows a reading note on its own", () => {
    expect(draw({ uncertain_pages: [3], page_meta: [] })).toContain("Page 3 may contain mistakes");
    const note = draw({ uncertain_pages: [], reading_note: "Read by an AI reader." });
    expect(note).toContain("Read by an AI reader.");
    expect(note).not.toContain("check against the original");
  });
});
