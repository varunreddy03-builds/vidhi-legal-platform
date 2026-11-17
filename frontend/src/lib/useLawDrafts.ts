import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api";

export interface DraftActs {
  acts: { act_id: string; title: string; count: number; historical: boolean }[];
  note: string;
  enabled: boolean;
  switched_off_note: string | null;
}

/** The Acts that have draft text. `enabled` is false while no written permission is recorded for the official text (INDIA_CODE_PERMISSION_REF), and then nothing about the law library is shown. */
export function useLawDrafts(signedIn = true) {
  return useQuery<DraftActs>({ queryKey: ["draft-acts"], queryFn: () => apiGet("/library/drafts/acts"), staleTime: 300_000, retry: false, enabled: signedIn });
}
