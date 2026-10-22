import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

/** CSRF token of the owner session every test starts with. */
export const TEST_CSRF = "csrf-from-the-session";

const ME = `${window.location.origin}/api/v1/auth/me`;

/** MSW server shared by the tests; each test adds its own handlers with `server.use`. By
 * default the owner is logged in; tests of the login flow override /auth/me with a 401. */
export const server = setupServer(
  http.get(ME, () =>
    HttpResponse.json({
      authenticated: true,
      kind: "session",
      csrf_token: TEST_CSRF,
      expires_at: "2030-01-01T00:00:00Z",
    }),
  ),
);
