import { useEffect, useRef, useState } from "react";

import { Brand } from "./Brand.jsx";
import { StatusDot } from "./StatusDot.jsx";
import { logIn, signUp } from "../lib/api.js";
import { cx } from "../lib/cx.js";
import {
  MAX_PASSWORD_LENGTH,
  MAX_USERNAME_LENGTH,
  validateCredentials,
} from "../lib/protocol.js";

const ACTIONS = [
  { id: "login", label: "Log in", submit: "Log in and join", busy: "Logging in..." },
  { id: "signup", label: "Sign up", submit: "Sign up and join", busy: "Signing up..." },
];

const FIELD_CLASS =
  "w-full rounded-xl border border-plum-200 bg-white px-3 py-2.5 text-plum-800 placeholder:text-plum-300 " +
  "dark:border-plum-800 dark:bg-plum-900 dark:text-plum-50 dark:placeholder:text-plum-500 " +
  "aria-invalid:border-rose-500";

export function AuthCard({ rooms, health, healthError, notice, onAuthenticated }) {
  const [action, setAction] = useState("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [room, setRoom] = useState(rooms[0]);
  const [showPassword, setShowPassword] = useState(false);
  const [invalidField, setInvalidField] = useState(null);
  const [error, setError] = useState(notice ?? "");
  const [busy, setBusy] = useState(false);
  const usernameRef = useRef(null);

  const current = ACTIONS.find((item) => item.id === action);
  const isSignup = action === "signup";

  useEffect(() => {
    if (!rooms.includes(room)) {
      setRoom(rooms[0]);
    }
  }, [rooms, room]);

  useEffect(() => {
    usernameRef.current?.focus();
  }, []);

  function switchAction(next) {
    setAction(next);
    setError("");
    setInvalidField(null);
  }

  async function handleSubmit(event) {
    event.preventDefault();
    const trimmedUsername = username.trim();
    setError("");
    setInvalidField(null);

    const problem = validateCredentials(action, trimmedUsername, password);
    if (problem) {
      setInvalidField(problem.field);
      setError(problem.message);
      return;
    }

    setBusy(true);
    try {
      if (isSignup) {
        await signUp(trimmedUsername, password);
      }
      const session = await logIn(trimmedUsername, password);
      setPassword("");
      onAuthenticated({ token: session.token, username: session.username, room });
    } catch (submitError) {
      setError(submitError.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="grid min-h-dvh place-items-center p-4">
      <section className="w-full max-w-md rounded-2xl border border-plum-200 bg-white p-7 shadow-lg shadow-plum-800/5 dark:border-plum-800 dark:bg-plum-850 dark:shadow-black/40">
        <div className="flex items-center gap-3">
          <Brand />
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">TSPO Chat</h1>
            <p className="text-sm text-plum-500 dark:text-plum-300">Tel-Hai bootcamp checkpoint</p>
          </div>
        </div>

        <div role="tablist" aria-label="Choose action" className="mt-6 grid grid-cols-2 gap-1 rounded-xl bg-plum-100 p-1 dark:bg-plum-900">
          {ACTIONS.map((item) => (
            <button
              key={item.id}
              type="button"
              role="tab"
              aria-selected={action === item.id}
              onClick={() => switchAction(item.id)}
              className={cx(
                "rounded-lg px-3 py-2 text-sm font-semibold transition",
                action === item.id
                  ? "bg-white text-plum-800 shadow-sm dark:bg-plum-850 dark:text-plum-50"
                  : "text-plum-500 hover:text-plum-800 dark:text-plum-300 dark:hover:text-plum-50",
              )}
            >
              {item.label}
            </button>
          ))}
        </div>

        <form onSubmit={handleSubmit} noValidate className="mt-5 grid gap-4">
          <div className="grid gap-1.5">
            <label htmlFor="username" className="text-xs font-semibold text-plum-500 dark:text-plum-300">
              Username
            </label>
            <input
              id="username"
              ref={usernameRef}
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              type="text"
              autoComplete="username"
              spellCheck={false}
              maxLength={MAX_USERNAME_LENGTH}
              placeholder="yovel"
              aria-invalid={invalidField === "username"}
              aria-describedby="username-hint"
              className={FIELD_CLASS}
            />
            {isSignup && (
              <p id="username-hint" className="text-xs text-plum-400 dark:text-plum-400">
                3-16 characters: letters, numbers, _ or -
              </p>
            )}
          </div>

          <div className="grid gap-1.5">
            <label htmlFor="password" className="text-xs font-semibold text-plum-500 dark:text-plum-300">
              Password
            </label>
            <div className="flex gap-2">
              <input
                id="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                type={showPassword ? "text" : "password"}
                autoComplete={isSignup ? "new-password" : "current-password"}
                maxLength={MAX_PASSWORD_LENGTH}
                placeholder="••••••••"
                aria-invalid={invalidField === "password"}
                aria-describedby="password-hint"
                className={FIELD_CLASS}
              />
              <button
                type="button"
                onClick={() => setShowPassword((value) => !value)}
                aria-pressed={showPassword}
                className="shrink-0 rounded-xl border border-plum-200 px-3 text-sm text-plum-500 hover:text-plum-800 dark:border-plum-800 dark:text-plum-300 dark:hover:text-plum-50"
              >
                {showPassword ? "Hide" : "Show"}
              </button>
            </div>
            {isSignup && (
              <p id="password-hint" className="text-xs text-plum-400 dark:text-plum-400">
                8-128 characters
              </p>
            )}
          </div>

          <div className="grid gap-1.5">
            <label htmlFor="room" className="text-xs font-semibold text-plum-500 dark:text-plum-300">
              Room
            </label>
            <select
              id="room"
              value={room}
              onChange={(event) => setRoom(event.target.value)}
              className={FIELD_CLASS}
            >
              {rooms.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </div>

          <button
            type="submit"
            disabled={busy}
            className="rounded-xl bg-magenta-500 px-4 py-3 font-semibold text-white transition hover:bg-magenta-600 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy ? current.busy : current.submit}
          </button>

          {error && (
            <p role="alert" className="rounded-xl bg-rose-50 px-3 py-2.5 text-sm text-rose-700 dark:bg-rose-950/60 dark:text-rose-300">
              {error}
            </p>
          )}
        </form>

        <p className="mt-5 flex items-center gap-2 border-t border-plum-200 pt-4 text-sm text-plum-500 dark:border-plum-800 dark:text-plum-300">
          <StatusDot tone={health ? "online" : healthError ? "offline" : "connecting"} />
          {health
            ? `Server online - ${health.connected_clients} connected`
            : healthError
              ? "Server offline"
              : "Checking server..."}
        </p>
      </section>
    </main>
  );
}
