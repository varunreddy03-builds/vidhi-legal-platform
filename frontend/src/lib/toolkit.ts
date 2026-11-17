import { CalendarClock, FileSearch, ListOrdered, Scale, ShieldCheck, type LucideIcon } from "lucide-react";
import type { Key } from "@/lib/i18n/en";

export type Tool = { id: string; icon: LucideIcon; title: Key; body: Key };

// The five tools of VIDHI Legal Katalyst, in the owner's order. Only Authority Check is built (behind its switch); the others are plain notices of what is planned.
export const TOOLS: Tool[] = [
  { id: "authority", icon: ShieldCheck, title: "toolkit.ac.title", body: "toolkit.ac.body" },
  { id: "deadlines", icon: CalendarClock, title: "toolkit.dl.title", body: "toolkit.dl.body" },
  { id: "oldcode", icon: Scale, title: "toolkit.oc.title", body: "toolkit.oc.body" },
  { id: "defects", icon: FileSearch, title: "toolkit.pf.title", body: "toolkit.pf.body" },
  { id: "dates", icon: ListOrdered, title: "toolkit.ld.title", body: "toolkit.ld.body" },
];
