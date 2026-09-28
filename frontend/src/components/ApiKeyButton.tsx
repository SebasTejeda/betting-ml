import { Check, KeyRound } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { getApiKey, setApiKey } from "@/lib/apiKey";

/** The write key is asked once and stored in this browser (personal, local tool). */
export function ApiKeyButton() {
  const [hasKey, setHasKey] = useState(() => Boolean(getApiKey()));
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState("");

  if (editing) {
    return (
      <form
        className="flex items-center gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          setApiKey(value.trim() || null);
          setHasKey(Boolean(value.trim()));
          setValue("");
          setEditing(false);
        }}
      >
        <label className="sr-only" htmlFor="api-key">
          Clave de escritura (APP_API_KEY)
        </label>
        <Input
          id="api-key"
          type="password"
          autoComplete="off"
          className="h-8 w-36 sm:w-44"
          placeholder="APP_API_KEY"
          value={value}
          onChange={(event) => setValue(event.target.value)}
        />
        <Button type="submit" size="sm">
          Guardar
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={() => setEditing(false)}>
          Cancelar
        </Button>
      </form>
    );
  }
  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      onClick={() => setEditing(true)}
      aria-label={hasKey ? "Clave configurada ✓" : "Configurar clave"}
    >
      {hasKey ? <Check aria-hidden className="text-positive" /> : <KeyRound aria-hidden />}
      <span className="hidden sm:inline">{hasKey ? "Clave configurada" : "Configurar clave"}</span>
    </Button>
  );
}
