import { useCallback, useEffect, useRef, useState } from "react";

import {
  MAX_MESSAGES_PER_WINDOW,
  MAX_MESSAGE_LENGTH,
  MESSAGE_WINDOW_MS,
  parseChatLine,
  systemTone,
  websocketUrl,
} from "../lib/protocol.js";

/**
 * Own the WebSocket handshake described in protocol.js.
 *
 * The connection is rebuilt whenever the token, the room or the reconnect
 * counter changes, because the server reads the room exactly once per socket.
 */
export function useChatSocket({
  token,
  username,
  room,
  websocketPort,
  websocketPath,
  maxMessageLength = MAX_MESSAGE_LENGTH,
  onSessionExpired,
}) {
  const [messages, setMessages] = useState([]);
  const [status, setStatus] = useState("connecting");
  const [statusText, setStatusText] = useState("Connecting...");
  const [attempt, setAttempt] = useState(0);

  const socketRef = useRef(null);
  const stageRef = useRef("idle");
  const closingRef = useRef(false);
  const nextIdRef = useRef(0);
  const sentAtRef = useRef([]);
  const expiredRef = useRef(onSessionExpired);

  useEffect(() => {
    expiredRef.current = onSessionExpired;
  }, [onSessionExpired]);

  const push = useCallback((message) => {
    nextIdRef.current += 1;
    const id = nextIdRef.current;
    setMessages((current) => [...current, { id, at: new Date(), ...message }]);
  }, []);

  // Each room keeps its own transcript, because the server never replays history.
  useEffect(() => {
    setMessages([]);
  }, [room, username]);

  useEffect(() => {
    if (!token) {
      return undefined;
    }

    let socket;
    try {
      socket = new WebSocket(websocketUrl({ port: websocketPort, path: websocketPath }));
    } catch {
      setStatus("offline");
      setStatusText("Cannot open connection");
      push({ kind: "system", tone: "error", text: "Could not open a WebSocket to the chat server." });
      return undefined;
    }

    socketRef.current = socket;
    stageRef.current = "handshake";
    closingRef.current = false;
    sentAtRef.current = [];
    setStatus("connecting");
    setStatusText("Connecting...");

    socket.onmessage = (event) => {
      if (socketRef.current !== socket) {
        return;
      }
      const text = String(event.data);

      if (stageRef.current === "handshake") {
        if (!text.startsWith("Anti-Bot passed: ")) {
          closingRef.current = true;
          push({ kind: "system", tone: "error", text });
          setStatus("blocked");
          setStatusText("Blocked before authentication");
          socket.close();
          return;
        }
        push({ kind: "system", tone: "success", text });
        socket.send(JSON.stringify({ token }));
        socket.send(JSON.stringify({ room }));
        stageRef.current = "joining";
        return;
      }

      if (stageRef.current === "joining") {
        if (!text.startsWith("Welcome ")) {
          closingRef.current = true;
          push({ kind: "system", tone: "error", text });
          socket.close();
          setStatus("offline");
          if (text.startsWith("Authentication failed")) {
            setStatusText("Session expired");
            expiredRef.current?.("Your session expired. Please log in again.");
          } else {
            setStatusText("Could not join the room");
          }
          return;
        }
        stageRef.current = "chatting";
        setStatus("online");
        setStatusText(`Connected to ${room}`);
        push({ kind: "system", tone: "success", text });
        return;
      }

      const chatLine = parseChatLine(text, room);
      if (chatLine) {
        push({ kind: "chat", sender: chatLine.sender, text: chatLine.body });
      } else {
        push({ kind: "system", tone: systemTone(text), text });
      }
    };

    socket.onerror = () => {
      if (socketRef.current === socket && stageRef.current === "handshake") {
        push({
          kind: "system",
          tone: "error",
          text:
            "The server refused the connection. Check that the chat server is running and that " +
            "this page was opened from an address the server allows.",
        });
      }
    };

    socket.onclose = (event) => {
      if (closingRef.current || socketRef.current !== socket) {
        return;
      }
      socketRef.current = null;
      stageRef.current = "idle";
      setStatus("offline");
      setStatusText("Disconnected");
      push({
        kind: "system",
        tone: "error",
        text: event.reason ? `Connection closed by the server: ${event.reason}` : "Connection closed.",
      });
    };

    return () => {
      closingRef.current = true;
      socketRef.current = null;
      stageRef.current = "idle";
      if (socket.readyState <= WebSocket.OPEN) {
        socket.close(1000, "Client closed");
      }
    };
  }, [token, room, websocketPort, websocketPath, attempt, push]);

  /** Send one chat line, applying the server limits locally first. */
  const sendMessage = useCallback(
    (text) => {
      const socket = socketRef.current;
      if (!socket || stageRef.current !== "chatting") {
        return false;
      }
      if (text.length > maxMessageLength) {
        push({
          kind: "system",
          tone: "error",
          text: `Message rejected: message cannot be longer than ${maxMessageLength} characters`,
        });
        return false;
      }

      const now = Date.now();
      sentAtRef.current = sentAtRef.current.filter((sent) => sent > now - MESSAGE_WINDOW_MS);
      if (sentAtRef.current.length >= MAX_MESSAGES_PER_WINDOW) {
        push({
          kind: "system",
          tone: "error",
          text: "Slow down: the server allows 20 messages every 10 seconds.",
        });
        return false;
      }

      sentAtRef.current.push(now);
      socket.send(text);
      return true;
    },
    [push, maxMessageLength],
  );

  const reconnect = useCallback(() => setAttempt((value) => value + 1), []);

  return { messages, status, statusText, sendMessage, reconnect };
}
