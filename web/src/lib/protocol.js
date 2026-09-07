/**
 * The wire contract with server/server.py.
 *
 * REST  POST /signup, POST /login -> { token }
 * WS    receive "Anti-Bot passed: ..." -> send {"token": ...} -> send {"room": ...}
 *       -> receive "Welcome ..." -> plain text messages in both directions
 *
 * Every limit here mirrors a constant in server/server.py so the UI can explain
 * a rejection before the server has to enforce it.
 */

export const MAX_MESSAGE_LENGTH = 500;
export const MAX_USERNAME_LENGTH = 16;
export const MIN_PASSWORD_LENGTH = 8;
export const MAX_PASSWORD_LENGTH = 128;
export const MAX_MESSAGES_PER_WINDOW = 20;
export const MESSAGE_WINDOW_MS = 10_000;

export const DEFAULT_ROOMS = ["general", "secret-pizza"];
export const DEFAULT_WEBSOCKET_PORT = 8765;

export const SIGNUP_USERNAME_PATTERN = /^[A-Za-z0-9_-]{3,16}$/;
// validate_chat_message() rejects these, so the composer strips them first.
export const CONTROL_CHARACTERS = new RegExp("[\\u0000-\\u001f\\u007f]", "g");

const CHAT_LINE = /^\[([^\]]+)\] ([^:]+): ([\s\S]*)$/;
const ERROR_PREFIXES =
  /^(Message blocked:|Message rejected:|Authentication failed:|Join room failed:|Connection blocked:|Too many DLP violations)/;
const SUCCESS_PREFIXES = /^(Welcome |Anti-Bot passed:)/;

/** Split a broadcast line into a chat message, or return null for a notice. */
export function parseChatLine(text, room) {
  const match = CHAT_LINE.exec(text);
  if (!match || match[1] !== room) {
    return null;
  }
  return { sender: match[2], body: match[3] };
}

/** Pick the visual tone for a server notice. */
export function systemTone(text) {
  if (ERROR_PREFIXES.test(text)) return "error";
  if (SUCCESS_PREFIXES.test(text)) return "success";
  return "info";
}

/** Derive the chat WebSocket address from the page address. */
export function websocketUrl({ port, path }) {
  const scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
  // Behind a TLS proxy the socket shares port 443 with the page, so /health
  // hands back a path instead of a port.
  if (path) {
    return `${scheme}//${window.location.host}${path}`;
  }
  return `${scheme}//${window.location.hostname}:${port}`;
}

/** Mirrors validate_signup / validate_username in server/server.py. */
export function validateCredentials(action, username, password) {
  if (action === "signup") {
    if (!SIGNUP_USERNAME_PATTERN.test(username)) {
      return {
        field: "username",
        message: "Username must be 3-16 characters: letters, numbers, _ or -",
      };
    }
    if (password.length < MIN_PASSWORD_LENGTH || password.length > MAX_PASSWORD_LENGTH) {
      return {
        field: "password",
        message: `Password must be ${MIN_PASSWORD_LENGTH}-${MAX_PASSWORD_LENGTH} characters`,
      };
    }
    return null;
  }

  if (!username) {
    return { field: "username", message: "Username is required" };
  }
  if (username.length > MAX_USERNAME_LENGTH) {
    return {
      field: "username",
      message: `Username cannot be longer than ${MAX_USERNAME_LENGTH} characters`,
    };
  }
  if (!password) {
    return { field: "password", message: "Password is required" };
  }
  return null;
}
