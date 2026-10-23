import { LogOut } from "lucide-react";
import { useState } from "react";

import { useAuth } from "@/auth/context";
import { Button } from "@/components/ui/button";

export function LogoutButton() {
  const { logout } = useAuth();
  const [pending, setPending] = useState(false);
  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      disabled={pending}
      aria-label="Cerrar sesión"
      onClick={() => {
        setPending(true);
        // the local session ends even if the request fails (see AuthProvider.logout)
        logout().catch(() => setPending(false));
      }}
    >
      <LogOut aria-hidden />
      <span className="hidden sm:inline">Salir</span>
    </Button>
  );
}
