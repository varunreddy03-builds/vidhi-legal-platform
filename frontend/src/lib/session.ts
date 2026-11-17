import { queryClient } from "@/lib/queryClient";
import { apiPost } from "@/lib/api";

/** Session cache ownership: every sign-out goes through endSession(). */
export async function beginSession() {
  // Everything cached so far belongs to a signed-out visitor, including a cached "not signed in" from a private page they were turned away from.
  // Invalidating would leave that answer in place for screens that are not mounted yet, and they would send the person straight back to sign-in.
  queryClient.clear();
}

export async function endSession() {
  try {
    await apiPost("/auth/logout");
  } finally {
    queryClient.clear();
  }
}
