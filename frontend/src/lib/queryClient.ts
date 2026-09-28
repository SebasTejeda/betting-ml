import { QueryClient } from "@tanstack/react-query";

import { ApiError } from "../api/client";

export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        // client errors (4xx) are answers, not glitches: do not retry them
        retry: (count, error) => !(error instanceof ApiError && error.status < 500) && count < 2,
      },
    },
  });
}
