import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";

import { budget, comparator, leagues } from "../test/fixtures";
import { API, renderApp } from "../test/render";
import { server, TEST_CSRF } from "../test/server";

function base() {
  server.use(
    http.get(`${API}/leagues`, () => HttpResponse.json(leagues)),
    http.get(`${API}/odds/budget`, () => HttpResponse.json(budget)),
  );
}

test("shows the best odds, margins and the experimental label", async () => {
  base();
  let accessible: string | null = null;
  server.use(
    http.get(`${API}/comparator`, ({ request }) => {
      accessible = new URL(request.url).searchParams.get("accessible_only");
      return HttpResponse.json(comparator);
    }),
  );
  renderApp("/");
  const table = await screen.findByRole("list", { name: "Partidos" });
  expect(within(table).getAllByText("Arsenal – Chelsea")[0]).toBeInTheDocument();
  expect(within(table).getAllByText("4.60")).toHaveLength(2);
  expect(within(table).getAllByText("Pagan +4.1 % vs promedio")).toHaveLength(2);
  expect(within(table).getByText("EXPERIMENTAL — solo papel")).toBeInTheDocument();
  expect(within(table).getAllByText("justa 4.35")).toHaveLength(1);
  expect(within(table).getByText("el modelo coincide")).toBeInTheDocument();
  expect(within(table).getByText("Sin cuota de referencia")).toBeInTheDocument();
  expect(screen.queryByText(/recomendad/i)).not.toBeInTheDocument();
  const signal = within(table).getByRole("link", { name: /anotar en papel/ });
  expect(signal).toHaveAttribute("href", expect.stringContaining("signal=1"));
  expect(accessible).toBe("true");
  expect(screen.getByText(/Créditos: 498/)).toBeInTheDocument();
});

test("empty day", async () => {
  base();
  server.use(
    http.get(`${API}/comparator`, () =>
      HttpResponse.json({ ...comparator, count: 0, matches: [] }),
    ),
  );
  renderApp("/");
  expect(await screen.findByText(/No hay partidos con cuotas/)).toBeInTheDocument();
});

test("API error is shown", async () => {
  base();
  server.use(
    http.get(`${API}/comparator`, () =>
      HttpResponse.json(
        { error: { code: "VALIDATION_ERROR", message: "fecha inválida", details: {} } },
        { status: 422 },
      ),
    ),
  );
  renderApp("/");
  expect(await screen.findByRole("alert")).toHaveTextContent("fecha inválida");
});

test("refresh sends the session CSRF token and reports a low budget (429)", async () => {
  base();
  server.use(http.get(`${API}/comparator`, () => HttpResponse.json(comparator)));
  let csrf: string | null = null;
  let key: string | null = "unset";
  server.use(
    http.post(`${API}/odds/refresh`, ({ request }) => {
      csrf = request.headers.get("X-CSRF-Token");
      key = request.headers.get("X-API-Key");
      return HttpResponse.json(
        {
          error: {
            code: "ODDS_BUDGET_LOW",
            message: "Quedan 42 créditos (mínimo 50). Refresco bloqueado hasta el próximo ciclo.",
            details: {},
          },
        },
        { status: 429 },
      );
    }),
  );
  renderApp("/");
  await screen.findByRole("list", { name: "Partidos" });
  await userEvent.click(screen.getByRole("button", { name: "Actualizar cuotas" }));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Quedan 42 créditos"));
  expect(csrf).toBe(TEST_CSRF);
  expect(key).toBeNull(); // no secret lives in the browser
});

test("the accessible filter can be turned off", async () => {
  base();
  const seen: string[] = [];
  server.use(
    http.get(`${API}/comparator`, ({ request }) => {
      seen.push(new URL(request.url).searchParams.get("accessible_only") ?? "");
      return HttpResponse.json(comparator);
    }),
  );
  renderApp("/");
  await screen.findByRole("list", { name: "Partidos" });
  await userEvent.click(screen.getByLabelText("Solo casas accesibles desde Perú"));
  await waitFor(() => expect(seen).toContain("false"));
});

test("each match links to its analysis", async () => {
  base();
  server.use(http.get(`${API}/comparator`, () => HttpResponse.json(comparator)));
  renderApp("/");
  const links = await screen.findAllByRole("link", { name: /Analizar\s*Arsenal – Chelsea/ });
  expect(links[0]).toHaveAttribute(
    "href",
    "/analysis?home=Arsenal&away=Chelsea&match=E0-2026-10-10-arsenal-chelsea",
  );
});
