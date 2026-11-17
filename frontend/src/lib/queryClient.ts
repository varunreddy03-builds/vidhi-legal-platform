import { QueryClient } from "@tanstack/react-query";

// Exported so lib/session can wipe it at session boundaries — cached data outlives logout.
// By default the data library PAUSES a request made while the device is offline and waits for the connection, which looks like a button that does nothing. Saving and asking should
// fail at once with a message that says what to do (lib/interaction.ts describe), so mutations run whatever the device says; reading screens still waits and resumes by itself.
export const queryClient = new QueryClient({ defaultOptions: { mutations: { networkMode: "always" } } });
