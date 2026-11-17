import { afterEach, describe, expect, it, vi } from "vitest";

const apiPost = vi.fn();
vi.mock("@/lib/api", () => ({ apiPost: (...args: unknown[]) => apiPost(...args) }));

import { queryClient } from "./queryClient";
import { beginSession, endSession } from "./session";

afterEach(() => {
  apiPost.mockReset();
  queryClient.clear();
});

describe("sign-out", () => {
  it("asks the server to end the session and then clears every cached answer", async () => {
    apiPost.mockResolvedValue(undefined);
    queryClient.setQueryData(["matters"], [{ id: "m1" }]);
    await endSession();
    expect(apiPost).toHaveBeenCalledWith("/auth/logout");
    expect(queryClient.getQueryData(["matters"])).toBeUndefined();
  });

  it("clears the cache even when the server cannot be reached, so one person's data never stays for the next", async () => {
    apiPost.mockRejectedValue(new Error("offline"));
    queryClient.setQueryData(["matters"], [{ id: "m1" }]);
    await expect(endSession()).rejects.toThrow("offline");
    expect(queryClient.getQueryData(["matters"])).toBeUndefined();
  });
});

describe("sign-in", () => {
  it("forgets everything cached before sign-in, so the new person's data is fetched fresh", async () => {
    queryClient.setQueryData(["matters"], [{ id: "old" }]);
    await beginSession();
    expect(queryClient.getQueryData(["matters"])).toBeUndefined();
  });

  it("forgets a cached 'not signed in' answer, which would otherwise send the person straight back to sign-in", async () => {
    queryClient.setQueryData(["me"], null);
    await beginSession();
    expect(queryClient.getQueryState(["me"])).toBeUndefined();
  });
});
