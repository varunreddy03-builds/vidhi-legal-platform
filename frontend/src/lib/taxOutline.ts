// A reply outline for a tax notice, filled in by plain code from what the person typed. It contains NO statute, section, rate, limit or case: every legal point is a blank for the
// lawyer to fill from a source they have checked. (Rule: never invent law.)

export type NoticeInput = {
  authority: string;
  reference: string;
  noticeDate: string;
  period: string;
  taxpayer: string;
  sectionNamed: string; // exactly as the notice states it; typed by the person, never supplied by the program
  points: string[]; // the points the notice raises, one per line
  documents: string[]; // documents the client has
};

const clean = (s: string) => s.replace(/\s+/g, " ").trim();
const lines = (s: string) => s.split(/\r?\n/).map(clean).filter(Boolean);
export const toLines = lines;

export function buildOutline(i: NoticeInput): string {
  const blank = (label: string) => `[${label}: to be filled by the advocate]`;
  const pts = i.points.length ? i.points : ["[Point raised in the notice]"];
  const docs = i.documents.length ? i.documents : ["[List the documents the client has]"];
  const out: string[] = [];
  out.push("DRAFT OUTLINE: NOT FOR FILING. Every legal point below is a blank for the advocate to complete from sources the advocate has checked.", "");
  out.push(`To: ${clean(i.authority) || blank("Authority")}`);
  out.push(`Reference: ${clean(i.reference) || blank("Notice reference")}    Date of notice: ${clean(i.noticeDate) || blank("Date")}`);
  out.push(`Taxpayer: ${clean(i.taxpayer) || blank("Name")}    Period: ${clean(i.period) || blank("Period")}`);
  out.push(`Provision named in the notice (as written in the notice): ${clean(i.sectionNamed) || blank("Provision")}`, "");
  out.push("1. Introduction", "   Reply to the notice above, filed on behalf of the taxpayer. [Add the date of service and the date for reply as stated in the notice.]", "");
  out.push("2. Facts", "   [Facts, in date order, each with the document that shows it.]", "");
  out.push("3. Reply to each point");
  pts.forEach((p, n) => {
    out.push(`   3.${n + 1} Point raised: ${clean(p)}`, "        Facts relied on: [ ]", "        Documents: [ ]", `        Legal position: ${blank("Provision and authority, with the source checked")}`, "        Submission: [ ]");
  });
  out.push("", "4. Documents enclosed");
  docs.forEach((d, n) => out.push(`   ${n + 1}. ${clean(d)}`));
  out.push("", "5. Prayer", "   [What is asked of the authority.]", "", "6. Time and hearing", "   [Any request for time, a personal hearing or copies of material relied on.]", "");
  out.push("Signed: [Name of the authorised representative]    Date: [ ]    Place: [ ]");
  return out.join("\n");
}
