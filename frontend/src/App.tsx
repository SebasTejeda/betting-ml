import { lazy } from "react";
import { Route, Routes } from "react-router-dom";

import { Layout } from "./components/Layout";
import { BacktestPage } from "./pages/BacktestPage";
import { CalculatorPage } from "./pages/CalculatorPage";
import { SettingsPage } from "./pages/SettingsPage";
import { TodayPage } from "./pages/TodayPage";

// Pages with charts (Recharts) load on demand, keeping the first load small.
const MatchPage = lazy(() => import("./pages/MatchPage").then((m) => ({ default: m.MatchPage })));
const BetsPage = lazy(() => import("./pages/BetsPage").then((m) => ({ default: m.BetsPage })));

export function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<TodayPage />} />
        <Route path="match/:matchId" element={<MatchPage />} />
        <Route path="calculator" element={<CalculatorPage />} />
        <Route path="bets" element={<BetsPage />} />
        <Route path="backtest" element={<BacktestPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<p>Página no encontrada.</p>} />
      </Route>
    </Routes>
  );
}
