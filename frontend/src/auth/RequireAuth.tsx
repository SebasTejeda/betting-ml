import { Navigate, Outlet, useLocation } from "react-router-dom";

import { Loading } from "@/components/common";

import { useAuth } from "./context";

/** Private pages: without a session, go to /login and come back here afterwards. */
export function RequireAuth() {
  const { status } = useAuth();
  const location = useLocation();
  if (status === "checking") return <Loading what="la sesión" />;
  if (status === "anonymous") {
    return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  }
  return <Outlet />;
}
