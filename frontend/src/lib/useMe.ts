import { useQuery } from "@tanstack/react-query";
import { ApiError, apiGet } from "@/lib/api";
import type { Entitlement, UserOut } from "@/lib/types";

export function useMe() {
  return useQuery<UserOut | null>({
    queryKey: ["me"],
    queryFn: async () => {
      try {
        return await apiGet<UserOut>("/auth/me");
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return null; // really signed out
        throw e; // a network failure or a server error is NOT "signed out": the person stays on the page (the offline banner explains) and it is retried when the connection returns
      }
    },
    retry: (count, e) => !(e instanceof ApiError) && count < 2,
    staleTime: 30_000,
  });
}

/** True when the signed-in role has the capability. Only hides buttons: the server is what actually refuses. */
export function useCan(capability: string): boolean {
  const { data } = useMe();
  return !!data?.capabilities?.includes(capability);
}

export function useEntitlement() {
  return useQuery<Entitlement | null>({
    queryKey: ["entitlement"],
    queryFn: async () => {
      try {
        return await apiGet<Entitlement>("/auth/entitlement");
      } catch {
        return null;
      }
    },
    retry: false,
    staleTime: 30_000,
  });
}

export interface LogoResponse {
  has_logo: boolean;
  data_url: string | null;
}

export function useLogo() {
  return useQuery<LogoResponse | null>({
    queryKey: ["org-logo"],
    queryFn: async () => {
      try {
        return await apiGet<LogoResponse>("/org/logo");
      } catch {
        return null;
      }
    },
    retry: false,
    staleTime: 60_000,
  });
}
