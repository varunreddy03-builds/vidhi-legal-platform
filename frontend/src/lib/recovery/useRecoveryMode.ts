import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api";

/** The one Legal Recovery switch (backend RECOVERY_FULL_FLOW, lib/recovery_mode.py). Off by default: the small free helper. While the answer is loading, or if it cannot be
 * read, the extra parts stay hidden. */
export function useRecoveryMode(): { full: boolean; ready: boolean } {
  const q = useQuery({ queryKey: ["recovery-options"], queryFn: () => apiGet<{ full_flow: boolean }>("/recovery/options"), staleTime: 5 * 60_000, retry: 1 });
  return { full: q.data?.full_flow === true, ready: !q.isLoading };
}
