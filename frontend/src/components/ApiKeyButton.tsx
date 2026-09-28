import { useState } from "react";

import { getApiKey, setApiKey } from "../lib/apiKey";

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
        <input
          id="api-key"
          type="password"
          autoComplete="off"
          className="w-40 rounded border border-slate-300 px-2 py-1 text-sm"
          placeholder="APP_API_KEY"
          value={value}
          onChange={(event) => setValue(event.target.value)}
        />
        <button type="submit" className="rounded bg-slate-900 px-2 py-1 text-sm text-white">
          Guardar
        </button>
        <button
          type="button"
          className="text-sm text-slate-700 underline"
          onClick={() => setEditing(false)}
        >
          Cancelar
        </button>
      </form>
    );
  }
  return (
    <button
      type="button"
      className="rounded border border-slate-300 px-2 py-1 text-sm text-slate-700 hover:bg-slate-100"
      onClick={() => setEditing(true)}
    >
      {hasKey ? "Clave configurada ✓" : "Configurar clave"}
    </button>
  );
}
