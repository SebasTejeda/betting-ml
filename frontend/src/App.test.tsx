import { screen } from "@testing-library/react";

import { renderApp } from "./test/render";

test("renders the navigation and the responsible gambling notice", async () => {
  renderApp("/backtest");
  const nav = await screen.findByRole("navigation", { name: "Principal" });
  for (const label of ["Hoy", "Calculadora", "Mis apuestas", "Backtest", "Ajustes"]) {
    expect(nav).toHaveTextContent(label);
  }
  expect(screen.getByText(/Juego responsable/)).toBeInTheDocument();
});

test("unknown routes show a not found message", async () => {
  renderApp("/nope");
  expect(await screen.findByText("Página no encontrada.")).toBeInTheDocument();
});
