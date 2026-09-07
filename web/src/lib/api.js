/** Thin client for the Python REST API. The UI is always served same-origin. */

const UNREACHABLE = "Cannot reach the chat server. Check that the server is running.";

async function readJson(response) {
  try {
    return await response.json();
  } catch {
    // A missing or non-JSON body is reported through the status code instead.
    return {};
  }
}

export async function postJson(path, payload) {
  let response;
  try {
    response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch {
    throw new Error(UNREACHABLE);
  }

  const data = await readJson(response);
  if (!response.ok) {
    throw new Error(data.error || `Request failed with status ${response.status}`);
  }
  return data;
}

export async function fetchHealth() {
  const response = await fetch("/health", { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Health check failed with status ${response.status}`);
  }
  return response.json();
}

export const signUp = (username, password) => postJson("/signup", { username, password });
export const logIn = (username, password) => postJson("/login", { username, password });
