import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";

import { settings } from "../test/fixtures";
import { API, renderApp } from "../test/render";
import { server } from "../test/server";

const report = {
  level: "Mínimo (backtest)",
  conclusion: "seguir con cambios",
  primary_strategy: "b365|none",
  test: {
    season: "2025-26",
    results: {
      "b365|none": {
        scenario: "b365",
        variant: "none",
        threshold: 0.03,
        n_bets: 27,
        roi_flat: -0.3,
        roi_ci_low: -0.8,
        roi_ci_high: 0.2,
        clv_mean: -0.0374,
        clv_ci_low: -0.08,
        clv_ci_high: 0.01,
        clv_positive_rate: 0.4,
      },
      "b365|champion": {
        scenario: "b365",
        variant: "champion",
        threshold: 0.03,
        n_bets: 8,
        roi_flat: 0.1,
        roi_ci_low: -0.9,
        roi_ci_high: 1.2,
        clv_mean: 0.0108,
        clv_ci_low: -0.05,
        clv_ci_high: 0.07,
        clv_positive_rate: 0.5,
      },
    },
  },
  margins: {
    validation_seasons: ["2022-23", "2023-24", "2024-25"],
    current_season: "2026-27",
    validation: {
      margins: {
        avg: { n_matches: 5330, margin_mean: 0.045 },
        max: { n_matches: 5321, margin_mean: 0.0047 },
      },
      best_vs_avg: { uplift_mean: 0.0499, uplift_median: 0.042 },
    },
    current: {
      margins: {
        avg: { n_matches: 250, margin_mean: 0.0647 },
        max: { n_matches: 242, margin_mean: 0.0267 },
      },
      best_vs_avg: { uplift_mean: 0.0485, uplift_median: 0.036 },
    },
  },
};

test("backtest shows the conclusion, the margins and flags E12 as not validated", async () => {
  server.use(http.get(`${API}/backtest/pinnacle`, () => HttpResponse.json(report)));
  renderApp("/backtest");
  expect(await screen.findByText("seguir con cambios")).toBeInTheDocument();
  expect(screen.getByText("+5.0 %")).toBeInTheDocument();
  expect(screen.getByText("4.5 %")).toBeInTheDocument();
  expect(screen.getByText(/filtro del modelo E12 \(no validado\)/)).toBeInTheDocument();
  expect(screen.getByText("-3.74 %")).toBeInTheDocument();
  expect(screen.queryByText(/recomendad/i)).not.toBeInTheDocument();
});

test("backtest not run yet", async () => {
  server.use(
    http.get(`${API}/backtest/pinnacle`, () =>
      HttpResponse.json(
        { error: { code: "BACKTEST_NOT_FOUND", message: "no", details: {} } },
        { status: 404 },
      ),
    ),
  );
  renderApp("/backtest");
  expect(await screen.findByText(/Aún no se ha ejecutado el backtest final/)).toBeInTheDocument();
});

test("settings are saved as fractions and a raised limit applies next month", async () => {
  let body: Record<string, unknown> = {};
  server.use(
    http.get(`${API}/settings`, () => HttpResponse.json(settings)),
    http.put(`${API}/settings`, async ({ request }) => {
      body = (await request.json()) as Record<string, unknown>;
      return HttpResponse.json({ ...settings, ...body, monthly_loss_limit_in_force: 100 });
    }),
  );
  renderApp("/settings");
  const limit = await screen.findByLabelText(/Límite de pérdida mensual/);
  expect(screen.getByLabelText(/Stake máximo/)).toHaveValue("2");
  await userEvent.clear(limit);
  await userEvent.type(limit, "150");
  await userEvent.click(screen.getByRole("button", { name: "Guardar" }));
  expect(await screen.findByText("Ajustes guardados.")).toBeInTheDocument();
  expect(body).toMatchObject({
    monthly_loss_limit: 150,
    max_stake_pct: 0.02,
    kelly_fraction: 0.25,
    min_edge: 0.02,
    currency: "PEN",
  });
  expect(
    screen.getByText(/el nuevo límite de .* aplica desde el mes siguiente/),
  ).toBeInTheDocument();
});

test("settings validation, and a 401 (expired session) leads to the login page", async () => {
  server.use(
    http.get(`${API}/settings`, () => HttpResponse.json(settings)),
    http.put(`${API}/settings`, () =>
      HttpResponse.json(
        {
          error: {
            code: "UNAUTHORIZED",
            message: "Credenciales inválidas o ausentes",
            details: {},
          },
        },
        { status: 401 },
      ),
    ),
  );
  renderApp("/settings");
  const stake = await screen.findByLabelText(/Stake máximo/);
  await userEvent.clear(stake);
  await userEvent.type(stake, "500");
  await userEvent.click(screen.getByRole("button", { name: "Guardar" }));
  expect(await screen.findByText("Máximo 100 %")).toBeInTheDocument();
  await userEvent.clear(stake);
  await userEvent.type(stake, "2");
  await userEvent.click(screen.getByRole("button", { name: "Guardar" }));
  expect(await screen.findByRole("form", { name: "Iniciar sesión" })).toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent("Tu sesión expiró");
});

test("a CSRF token rotated by another tab is refreshed, so the retry is saved", async () => {
  let meCalls = 0;
  const sent: (string | null)[] = [];
  server.use(
    http.get(`${API}/auth/me`, () => {
      meCalls += 1;
      return HttpResponse.json({
        authenticated: true,
        kind: "session",
        csrf_token: meCalls === 1 ? "stale-token" : "rotated-token",
        expires_at: "2030-01-01T00:00:00Z",
      });
    }),
    http.get(`${API}/settings`, () => HttpResponse.json(settings)),
    http.put(`${API}/settings`, ({ request }) => {
      const csrf = request.headers.get("X-CSRF-Token");
      sent.push(csrf);
      return csrf === "rotated-token"
        ? HttpResponse.json(settings)
        : HttpResponse.json(
            {
              error: {
                code: "CSRF_FAILED",
                message: "Falta el token CSRF o no corresponde a la sesión",
                details: {},
              },
            },
            { status: 403 },
          );
    }),
  );
  renderApp("/settings");
  await screen.findByLabelText(/Stake máximo/);
  await userEvent.click(screen.getByRole("button", { name: "Guardar" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Vuelve a intentarlo.");
  await userEvent.click(screen.getByRole("button", { name: "Guardar" }));
  expect(await screen.findByText("Ajustes guardados.")).toBeInTheDocument();
  expect(sent).toEqual(["stale-token", "rotated-token"]);
  expect(screen.queryByRole("form", { name: "Iniciar sesión" })).not.toBeInTheDocument();
});
