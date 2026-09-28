import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";

import { MATCH_ID, bookmakers, calculation, detail } from "../test/fixtures";
import { API, renderApp } from "../test/render";
import { server } from "../test/server";

test("shows every bookmaker, highlights the best price and the margins", async () => {
  server.use(
    http.get(`${API}/comparator/${MATCH_ID}`, () => HttpResponse.json(detail)),
    http.get(`${API}/bookmakers`, () => HttpResponse.json(bookmakers)),
  );
  renderApp(`/match/${MATCH_ID}`);
  expect(await screen.findByRole("heading", { name: "Arsenal – Chelsea" })).toBeInTheDocument();
  const table = screen.getByRole("table");
  const betsson = within(table).getByRole("row", { name: /betsson/ });
  expect(within(betsson).getAllByText("(mejor cuota)", { exact: false })).toHaveLength(2);
  expect(within(table).getByText("1.7 %")).toBeInTheDocument();
  expect(screen.getByRole("img", { name: /cuota de referencia/ })).toBeInTheDocument();
  expect(screen.getByText("Justa (pinnacle): 4.35 · 23.0 %")).toBeInTheDocument();
  expect(screen.getByText("Modelo (E12-test): 24.0 %")).toBeInTheDocument();
  expect(screen.getByText("EXPERIMENTAL — solo papel")).toBeInTheDocument();
});

test("quick calculator only offers manual bookmakers and shows the result", async () => {
  let body: unknown = null;
  server.use(
    http.get(`${API}/comparator/${MATCH_ID}`, () => HttpResponse.json(detail)),
    http.get(`${API}/bookmakers`, () => HttpResponse.json(bookmakers)),
    http.post(`${API}/calculator`, async ({ request }) => {
      body = await request.json();
      return HttpResponse.json(calculation);
    }),
  );
  renderApp(`/match/${MATCH_ID}`);
  const casa = await screen.findByLabelText("Casa");
  await screen.findByRole("option", { name: "Te Apuesto" });
  expect(within(casa).queryByRole("option", { name: "Pinnacle" })).not.toBeInTheDocument();
  await userEvent.selectOptions(screen.getByLabelText("Resultado"), "away");
  await userEvent.selectOptions(casa, "teapuesto");
  await userEvent.type(screen.getByLabelText("Cuota"), "4.4");
  await userEvent.click(screen.getByRole("button", { name: "Evaluar" }));
  const result = await screen.findByRole("region", { name: "Resultado" });
  expect(result).toHaveTextContent("Cuota justa (pinnacle): 4.35");
  expect(result).toHaveTextContent("cerca de la cuota justa");
  expect(body).toEqual({ match_id: MATCH_ID, outcome: "away", bookmaker: "teapuesto", odds: 4.4 });
});

test("invalid odds are rejected before calling the API", async () => {
  server.use(
    http.get(`${API}/comparator/${MATCH_ID}`, () => HttpResponse.json(detail)),
    http.get(`${API}/bookmakers`, () => HttpResponse.json(bookmakers)),
  );
  renderApp(`/match/${MATCH_ID}`);
  await screen.findByRole("option", { name: "Te Apuesto" });
  await userEvent.selectOptions(screen.getByLabelText("Casa"), "teapuesto");
  await userEvent.type(screen.getByLabelText("Cuota"), "0.9");
  await userEvent.click(screen.getByRole("button", { name: "Evaluar" }));
  expect(await screen.findByText("La cuota debe ser mayor que 1")).toBeInTheDocument();
});

test("unknown match", async () => {
  server.use(
    http.get(`${API}/comparator/nope`, () =>
      HttpResponse.json(
        { error: { code: "MATCH_NOT_FOUND", message: "no", details: {} } },
        { status: 404 },
      ),
    ),
  );
  renderApp("/match/nope");
  expect(await screen.findByText(/Partido no encontrado/)).toBeInTheDocument();
});
