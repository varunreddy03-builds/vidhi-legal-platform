import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe as suite, expect, it } from "vitest";
import ErrorBoundary from "@/components/ErrorBoundary";
import OfflineBanner from "@/components/OfflineBanner";
import { NetworkError } from "@/lib/api";
import { describe } from "@/lib/interaction";

suite("app essentials", () => {
  it("the error boundary switches to its calm fallback when a screen throws, and shows nothing technical", () => {
    expect(ErrorBoundary.getDerivedStateFromError()).toEqual({ failed: true });
    const boundary = new ErrorBoundary({ children: null });
    boundary.state = { failed: true };
    const html = renderToStaticMarkup(boundary.render() as React.ReactElement);
    expect(html).toContain("Something went wrong on this screen");
    expect(html).toContain('href="/start"');
    expect(html).not.toMatch(/stack|undefined|TypeError/i);
  });

  it("a healthy screen is passed through untouched", () => {
    const boundary = new ErrorBoundary({ children: createElement("p", null, "all good") });
    expect(renderToStaticMarkup(boundary.render() as React.ReactElement)).toBe("<p>all good</p>");
  });

  it("a failed network call is described as a connection problem, not a mystery", () => {
    expect(describe(new NetworkError())).toContain("Cannot reach VIDHI");
    expect(describe(new TypeError("x is undefined"))).toBe("Something went wrong. Try again."); // a programming error is not blamed on the connection
    expect(describe(new Error("anything else"))).toBe("Something went wrong. Try again.");
  });

  it("the offline banner renders nothing while online (server render assumes online)", () => {
    expect(renderToStaticMarkup(createElement(OfflineBanner))).toBe("");
  });
});
