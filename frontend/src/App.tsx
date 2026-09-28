import { Route, Routes } from "react-router-dom";

import { Layout } from "./components/Layout";
import { BacktestPage } from "./pages/BacktestPage";
import { BetsPage } from "./pages/BetsPage";
import { CalculatorPage } from "./pages/CalculatorPage";
import { MatchPage } from "./pages/MatchPage";
import { SettingsPage } from "./pages/SettingsPage";
import { TodayPage } from "./pages/TodayPage";

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
