import { expect, test } from "@playwright/test";
import { scan, signUp, unique } from "./helpers";

// A lawyer previews and publishes a graph for a client; the client sees a readable list. The browser tests cannot receive the invitation e-mail, so the client's page is shown with the
// server's replies supplied here. What a client may receive is decided and tested on the server (backend/tests/test_graph_share.py).

test("the firm previews, shares and stops sharing the graph", async ({ page }) => {
  await signUp(page);
  const m = await page.request.post("/api/matters", { data: { title: `Graph ${unique()}`, description: "", parties: "", jurisdiction_id: "IN" } });
  const matter = (await m.json()) as { id: string };
  const up = await page.request.post(`/api/matters/${matter.id}/documents`, { multipart: { file: { name: `letter-${unique()}.txt`, mimeType: "text/plain", buffer: Buffer.from(`Dear client ${unique()}\n`) } } });
  const doc = (await up.json()) as { id: string; filename: string };
  await page.goto(`/matters/${matter.id}`);
  await page.getByTestId("tab-client").click();
  const panel = page.getByTestId("portal-graph-panel");
  await expect(panel).toContainText("Not shared");
  await expect(page.getByTestId("portal-graph-preview-empty")).toBeVisible(); // nothing is shared with the client yet, so the preview has no document
  await page.request.post(`/api/matters/${matter.id}/portal/documents`, { data: { document_id: doc.id } });
  await page.reload();
  await page.getByTestId("tab-client").click();
  await expect(page.getByTestId("portal-graph-preview-doc")).toContainText(doc.filename);
  await scan(page, "Client tab with the graph preview");
  await page.getByTestId("portal-graph-publish").click();
  await expect(page.getByTestId("portal-graph-state")).toContainText("Clients see that snapshot");
  await page.getByTestId("portal-graph-withdraw").click();
  await expect(page.getByTestId("portal-graph-state")).toContainText("Not shared");
});

test("a client sees the shared graph as a readable list, on a phone too", async ({ page }) => {
  await signUp(page);
  const me = await (await page.request.get("/api/auth/me")).json();
  await page.route("**/api/auth/me", (r) => r.fulfill({ json: { ...me, role: "CLIENT", capabilities: ["account", "portal"] } }));
  await page.route("**/api/portal/matters", (r) => r.fulfill({ json: { firm: "Test Chambers", matters: [{ id: "m1", title: "A matter", status: "OPEN", updates: 0, documents: 1 }] } }));
  await page.route("**/api/portal/matters/m1", (r) => r.fulfill({ json: { firm: "Test Chambers", id: "m1", title: "A matter", status: "OPEN", updates: [], documents: [{ id: "d1", filename: "lease.pdf", shared_at: "2026-11-18T10:00:00+00:00" }], notice: "Read-only." } }));
  await page.route("**/api/portal/matters/m1/graph", (r) => r.fulfill({ json: { graph: { shared_at: "2026-11-18T10:00:00+00:00", shared_by: "A Lawyer", nodes: [
    { id: "m1", label: "A matter", node_type: "MATTER" }, { id: "d1", label: "lease.pdf", node_type: "DOCUMENT", sublabel: "CONTRACT" }, { id: "p1", label: "Asha Rao", node_type: "PERSON" }, { id: "e1", label: "2026-03-01 lease signed", node_type: "EVENT" }],
    edges: [{ source: "d1", target: "m1", relation: "PART_OF" }, { source: "d1", target: "p1", relation: "MENTIONS" }, { source: "e1", target: "d1", relation: "DERIVED_FROM" }] } } }));
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/portal?m=m1");
  const g = page.getByTestId("portal-graph-view-doc");
  await expect(g).toContainText("lease.pdf");
  await expect(g).toContainText("Asha Rao");
  await expect(g).toContainText("lease signed");
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
  await scan(page, "Client portal with the shared graph");
});
