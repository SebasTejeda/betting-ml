import { setupServer } from "msw/node";

/** MSW server shared by the tests; each test adds its own handlers with `server.use`. */
export const server = setupServer();
