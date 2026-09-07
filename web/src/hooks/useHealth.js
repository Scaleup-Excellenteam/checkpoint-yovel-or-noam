import { useCallback, useEffect, useState } from "react";

import { fetchHealth } from "../lib/api.js";

/** Poll /health once so the UI can show server state and the real room list. */
export function useHealth() {
  const [health, setHealth] = useState(null);
  const [error, setError] = useState(null);

  const refresh = useCallback(async () => {
    try {
      setHealth(await fetchHealth());
      setError(null);
    } catch (healthError) {
      setHealth(null);
      setError(healthError.message);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { health, error, refresh };
}
