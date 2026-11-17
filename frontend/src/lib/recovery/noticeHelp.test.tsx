import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import NoticeHelp from "@/components/recovery/NoticeHelp";
import { GUIDE_EN } from "./guideStrings";
import { ADVOCATE_TO_CONFIRM, NOTICE_HELP } from "./portalRules";

const SRC = path.resolve(__dirname, "../..");

describe("Legal Recovery help panel: How to write a payment notice", () => {
  const html = renderToStaticMarkup(<NoticeHelp />);

  it("renders the title, the four parts and every point from the config file", () => {
    expect(html).toContain("How to write a payment notice");
    expect(NOTICE_HELP.sections.map((s) => s.heading)).toEqual(["What it is", "Order of the letter", "Sending", "Style"]);
    for (const s of NOTICE_HELP.sections) {
      expect(html).toContain(s.heading);
      for (const p of s.points) expect(html).toContain(p.replace(/'/g, "&#x27;"));
    }
    expect(html).toContain("<ol"); // the order of the letter is a numbered list
  });

  it("marks every point of law 'advocate to confirm' and states no law itself", () => {
    expect(NOTICE_HELP.lawPoints).toHaveLength(4);
    expect(html.split(`>${ADVOCATE_TO_CONFIRM}<`).length - 1).toBe(NOTICE_HELP.lawPoints.length);
    const everything = [NOTICE_HELP.lawIntro, ...NOTICE_HELP.lawPoints, ...NOTICE_HELP.sections.flatMap((s) => s.points)].join(" ");
    expect(everything).not.toMatch(/section\s+\d+|\d+\s*%|per cent|three times|compound|within 45 days|is mandatory|you must|you are entitled/i); // no section number, rate or rule is asserted
    expect(everything).not.toMatch(/\b(lied|liar|fraud|cheat)/i); // neutral wording
  });

  it("keeps the panel's words in the one config file, not in the screen", () => {
    const screen = fs.readFileSync(path.join(SRC, "components", "recovery", "NoticeHelp.tsx"), "utf8");
    for (const p of [NOTICE_HELP.title, ...NOTICE_HELP.lawPoints, ...NOTICE_HELP.sections.flatMap((s) => s.points)]) expect(screen.includes(p)).toBe(false);
  });

  it("the guide says it is a guide, not legal advice", () => {
    expect(GUIDE_EN.tagline).toBe("A guide, not legal advice.");
  });
});
