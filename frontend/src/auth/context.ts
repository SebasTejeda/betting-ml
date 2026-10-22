import { createContext, useContext } from "react";

export type AuthStatus = "checking" | "anonymous" | "authenticated";

export type AuthState = {
  status: AuthStatus;
  /** True when the last session ended because the API answered 401 (expired or revoked). */
  expired: boolean;
  login: (password: string) => Promise<void>;
  logout: () => Promise<void>;
};

export const AuthContext = createContext<AuthState | null>(null);

export function useAuth(): AuthState {
  const state = useContext(AuthContext);
  if (!state) throw new Error("useAuth must be used inside <AuthProvider>");
  return state;
}
