import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api";

type SignInOptions = { google: boolean; turnstile_site_key: string | null; signup_mode: string; recovery?: boolean };

/** Whether Legal Recovery is part of this installation (backend RECOVERY_ENABLED, lib/recovery_mode.py). It is NOT by default: every menu entry, page and link to it is hidden.
 * Read from the public sign-in options (the same answer the login page uses), so it also works before sign-in. While the answer is loading, or if it cannot be read, Recovery stays hidden. */
export function useRecoveryEnabled(): { enabled: boolean; ready: boolean } {
  const q = useQuery({ queryKey: ["sign-in-options"], queryFn: () => apiGet<SignInOptions>("/auth/options"), staleTime: 5 * 60_000, retry: 1 });
  return { enabled: q.data?.recovery === true, ready: !q.isLoading };
}
