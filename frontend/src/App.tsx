import { lazy } from "react";
import { Route, Routes } from "react-router-dom";

import { RequireAuth } from "./auth/RequireAuth";
import { Layout } from "./components/Layout";
import { BacktestPage } from "./pages/BacktestPage";
import { CalculatorPage } from "./pages/CalculatorPage";
import { LoginPage } from "./pages/LoginPage";
import { SettingsPage } from "./pages/SettingsPage";
import { TodayPage } from "./pages/TodayPage";
import { TopPage } from "./pages/TopPage";

// Pages with charts (Recharts) load on demand, keeping the first load small.
const MatchPage = lazy(() => import("./pages/MatchPage").then((m) => ({ default: m.MatchPage })));
const BetsPage = lazy(() => import("./pages/BetsPage").then((m) => ({ default: m.BetsPage })));
const AnalysisPage = lazy(() =>
  import("./pages/AnalysisPage").then((m) => ({ default: m.AnalysisPage })),
);

export function App() {
  return (
    <Routes>
      <Route path="login" element={<LoginPage />} />
      <Route element={<RequireAuth />}>
        <Route element={<Layout />}>
          <Route index element={<TodayPage />} />
          <Route path="top" element={<TopPage />} />
          <Route path="match/:matchId" element={<MatchPage />} />
          <Route path="analysis" element={<AnalysisPage />} />
          <Route path="calculator" element={<CalculatorPage />} />
          <Route path="bets" element={<BetsPage />} />
          <Route path="backtest" element={<BacktestPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="*" element={<p>Página no encontrada.</p>} />
        </Route>
      </Route>
    </Routes>
  );
}
