export type SharedGraphData = { nodes: { id: string; label: string; node_type: string; sublabel?: string | null }[]; edges: { source: string; target: string; relation: string }[] };

// A shared graph as a readable list: each document with the people and dates found in it. A list, not a drawing, so it reads the same on a phone and with a screen reader.
export default function SharedGraph({ graph, testId = "shared-graph" }: { graph: SharedGraphData; testId?: string }) {
  const byId = new Map(graph.nodes.map((n) => [n.id, n]));
  const docs = graph.nodes.filter((n) => n.node_type === "DOCUMENT");
  const linked = (docId: string, relation: string, type: string, from: "source" | "target") =>
    graph.edges.filter((e) => e.relation === relation && e[from === "source" ? "target" : "source"] === docId).map((e) => byId.get(e[from])).filter((n) => n?.node_type === type);
  if (docs.length === 0) return <p className="text-sm text-muted-foreground" data-testid={`${testId}-empty`}>No documents are in this view yet.</p>;
  return (
    <ul className="space-y-2" data-testid={testId}>
      {docs.map((d) => {
        const people = graph.edges.filter((e) => e.relation === "MENTIONS" && e.source === d.id).map((e) => byId.get(e.target)).filter((n) => n?.node_type === "PERSON");
        const dates = linked(d.id, "DERIVED_FROM", "EVENT", "source");
        return (
          <li key={d.id} className="rounded-lg border bg-background/40 p-3 text-sm" data-testid={`${testId}-doc`}>
            <p className="font-medium break-all">{d.label}{d.sublabel ? <span className="ml-2 text-xs font-normal text-muted-foreground">{d.sublabel.toLowerCase()}</span> : null}</p>
            {people.length > 0 && <p className="mt-1 text-muted-foreground">People named: {people.map((p) => p!.label).join(", ")}</p>}
            {dates.length > 0 && <ul className="mt-1 list-disc pl-5 text-muted-foreground">{dates.map((e) => <li key={e!.id}>{e!.label}</li>)}</ul>}
            {people.length === 0 && dates.length === 0 && <p className="mt-1 text-muted-foreground">No people or dates found in it.</p>}
          </li>
        );
      })}
    </ul>
  );
}
