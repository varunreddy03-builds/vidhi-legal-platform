import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import PilotBanner from "./PilotBanner";

const draw = (show: boolean) => renderToStaticMarkup(<MemoryRouter><PilotBanner show={show} /></MemoryRouter>);

describe("pilot banner", () => {
  it("tells a pilot account to use sample or public drafts only and links to the feedback form", () => {
    const html = draw(true);
    expect(html).toContain("sample or public drafts only");
    expect(html).toContain("never client papers");
    expect(html).toContain('href="/feedback"');
  });
  it("shows nothing on an ordinary account", () => {
    expect(draw(false)).toBe("");
  });
});
