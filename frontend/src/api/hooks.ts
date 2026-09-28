import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "./client";
import type { BetIn, BetPatch, CalculatorIn, SettingsIn } from "./types";

export const keys = {
  leagues: ["leagues"] as const,
  budget: ["odds", "budget"] as const,
  bookmakers: ["bookmakers"] as const,
  comparator: (params: ComparatorParams) => ["comparator", params] as const,
  detail: (matchId: string) => ["comparator", "detail", matchId] as const,
  bets: (params: BetsParams) => ["bets", "list", params] as const,
  summary: (kind: SummaryKind) => ["bets", "summary", kind] as const,
  settings: ["settings"] as const,
  backtest: ["backtest"] as const,
};

export type ComparatorParams = { date: string; league?: string; accessibleOnly: boolean };
export type BetsParams = {
  kind?: "real" | "paper";
  status?: "pendiente" | "ganada" | "perdida" | "nula";
  page: number;
};
export type SummaryKind = "real" | "paper" | "all";

export function useLeagues() {
  return useQuery({
    queryKey: keys.leagues,
    queryFn: () => unwrap(api.GET("/api/v1/leagues")),
    staleTime: Infinity,
  });
}

export function useBudget() {
  return useQuery({
    queryKey: keys.budget,
    queryFn: () => unwrap(api.GET("/api/v1/odds/budget")),
  });
}

export function useBookmakers() {
  return useQuery({
    queryKey: keys.bookmakers,
    queryFn: () => unwrap(api.GET("/api/v1/bookmakers")),
    staleTime: Infinity,
  });
}

export function useComparator(params: ComparatorParams) {
  return useQuery({
    queryKey: keys.comparator(params),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/comparator", {
          params: {
            query: {
              date: params.date,
              league: params.league || undefined,
              accessible_only: params.accessibleOnly,
            },
          },
        }),
      ),
  });
}

export function useMatchDetail(matchId: string) {
  return useQuery({
    queryKey: keys.detail(matchId),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/comparator/{match_id}", {
          params: { path: { match_id: matchId } },
        }),
      ),
  });
}

export function useRefreshOdds() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (league?: string) =>
      unwrap(
        api.POST("/api/v1/odds/refresh", { params: { query: { league: league || undefined } } }),
      ),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: ["odds"] });
      void client.invalidateQueries({ queryKey: ["comparator"] });
    },
  });
}

export function useCalculator() {
  return useMutation({
    mutationFn: (body: CalculatorIn) => unwrap(api.POST("/api/v1/calculator", { body })),
  });
}

export function useCreateBet() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: BetIn) => unwrap(api.POST("/api/v1/bets", { body })),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["bets"] }),
  });
}

export function useBets(params: BetsParams) {
  return useQuery({
    queryKey: keys.bets(params),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/bets", {
          params: {
            query: { kind: params.kind, status: params.status, page: params.page, size: 20 },
          },
        }),
      ),
  });
}

export function useSummary(kind: SummaryKind) {
  return useQuery({
    queryKey: keys.summary(kind),
    queryFn: () => unwrap(api.GET("/api/v1/bets/summary", { params: { query: { kind } } })),
  });
}

export function useUpdateBet() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, patch }: { id: number; patch: BetPatch }) =>
      unwrap(api.PATCH("/api/v1/bets/{bet_id}", { params: { path: { bet_id: id } }, body: patch })),
    onSettled: () => void client.invalidateQueries({ queryKey: ["bets"] }),
  });
}

export function useDeleteBet() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      unwrap(api.DELETE("/api/v1/bets/{bet_id}", { params: { path: { bet_id: id } } })),
    onSettled: () => void client.invalidateQueries({ queryKey: ["bets"] }),
  });
}

export function useSettleBets() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/bets/settle")),
    onSettled: () => void client.invalidateQueries({ queryKey: ["bets"] }),
  });
}

export function useSettings() {
  return useQuery({
    queryKey: keys.settings,
    queryFn: () => unwrap(api.GET("/api/v1/settings")),
  });
}

export function useSaveSettings() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: SettingsIn) => unwrap(api.PUT("/api/v1/settings", { body })),
    onSuccess: (data) => {
      client.setQueryData(keys.settings, data);
      void client.invalidateQueries({ queryKey: ["bets"] });
    },
  });
}

export function useBacktest() {
  return useQuery({
    queryKey: keys.backtest,
    queryFn: () => unwrap(api.GET("/api/v1/backtest/pinnacle")),
    staleTime: Infinity,
  });
}
