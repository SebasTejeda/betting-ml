import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";

import { API, renderApp } from "../test/render";
import { server } from "../test/server";

const NEW_CSRF = "csrf-of-the-new-session";

function error(status: number, code: string, message: string, headers?: Record<string, string>) {
  return HttpResponse.json({ error: { code, message, details: {} } }, { status, headers });
}

/** No session on load; /auth/login accepts "correct horse battery". */
function anonymous(): { logins: { password: string; credentials: string }[] } {
  const logins: { password: string; credentials: string }[] = [];
  server.use(
    http.get(`${API}/auth/me`, () =>
      error(401, "UNAUTHORIZED", "Credenciales inválidas o ausentes"),
    ),
    http.post(`${API}/auth/login`, async ({ request }) => {
      const { password } = (await request.json()) as { password: string };
      logins.push({ password, credentials: request.credentials });
      if (password !== "correct horse battery") {
        return error(401, "INVALID_CREDENTIALS", "Credenciales inválidas");
      }
      return HttpResponse.json({
        csrf_token: NEW_CSRF,
        expires_at: "2030-01-01T00:00:00Z",
        idle_minutes: 30,
      });
    }),
  );
  return { logins };
}

async function typePassword(value: string) {
  await userEvent.type(await screen.findByLabelText("Contraseña"), value);
  await userEvent.click(screen.getByRole("button", { name: "Entrar" }));
}

test("a private page without session goes to the login, and back after logging in", async () => {
  const { logins } = anonymous();
  renderApp("/nope");
  expect(await screen.findByRole("form", { name: "Iniciar sesión" })).toBeInTheDocument();
  expect(screen.queryByRole("navigation", { name: "Principal" })).not.toBeInTheDocument();
  expect(screen.queryByRole("status")).not.toBeInTheDocument(); // not an expiry

  await typePassword("wrong password");
  expect(await screen.findByRole("alert")).toHaveTextContent("Credenciales inválidas");
  expect(screen.getByLabelText("Contraseña")).toHaveValue(""); // the field is cleared

  await typePassword("correct horse battery");
  expect(await screen.findByText("Página no encontrada.")).toBeInTheDocument();
  expect(logins.map((l) => l.password)).toEqual(["wrong password", "correct horse battery"]);
  expect(logins.every((l) => l.credentials === "same-origin")).toBe(true);
});

test("nothing secret is stored in the browser and writes carry the in-memory CSRF token", async () => {
  anonymous();
  let csrf: string | null = null;
  server.use(
    http.post(`${API}/auth/logout`, ({ request }) => {
      csrf = request.headers.get("X-CSRF-Token");
      return new HttpResponse(null, { status: 204 });
    }),
  );
  renderApp("/nope");
  await typePassword("correct horse battery");
  await screen.findByText("Página no encontrada.");

  const stored = [
    ...Object.values({ ...window.localStorage }),
    ...Object.values({ ...window.sessionStorage }),
  ].join(" ");
  expect(stored).not.toContain(NEW_CSRF);
  expect(stored).not.toContain("correct horse battery");
  expect(document.cookie).toBe(""); // the session cookie is HttpOnly (set by the API)

  await userEvent.click(screen.getByRole("button", { name: "Cerrar sesión" }));
  expect(await screen.findByRole("form", { name: "Iniciar sesión" })).toBeInTheDocument();
  expect(csrf).toBe(NEW_CSRF);
  expect(screen.queryByRole("status")).not.toBeInTheDocument(); // own logout, not an expiry
});

test("too many attempts (429) shows the wait and blocks the button", async () => {
  anonymous();
  server.use(
    http.post(`${API}/auth/login`, () =>
      error(429, "TOO_MANY_ATTEMPTS", "Demasiados intentos", { "Retry-After": "60" }),
    ),
  );
  renderApp("/");
  await typePassword("guess");
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Demasiados intentos. Vuelve a intentarlo en 60 s.",
  );
  await userEvent.type(screen.getByLabelText("Contraseña"), "another");
  expect(screen.getByRole("button", { name: "Entrar" })).toBeDisabled();
});

test("login disabled on the server shows its message", async () => {
  anonymous();
  server.use(
    http.post(`${API}/auth/login`, () => error(503, "LOGIN_DISABLED", "Login no configurado")),
  );
  renderApp("/");
  await typePassword("anything");
  expect(await screen.findByRole("alert")).toHaveTextContent("Login no configurado");
});

test("with a session, the login page goes straight to the app", async () => {
  // the home page's data is irrelevant here; /auth/me falls through to the default session
  server.use(
    http.get(`${API}/*`, ({ request }) =>
      new URL(request.url).pathname.endsWith("/auth/me")
        ? undefined
        : error(500, "INTERNAL", "irrelevante"),
    ),
  );
  renderApp("/login");
  expect(await screen.findByRole("navigation", { name: "Principal" })).toBeInTheDocument();
  await waitFor(() =>
    expect(screen.queryByRole("form", { name: "Iniciar sesión" })).not.toBeInTheDocument(),
  );
});
