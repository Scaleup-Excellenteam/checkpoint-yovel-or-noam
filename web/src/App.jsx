import { useCallback, useEffect, useMemo, useState } from "react";

import { AuthCard } from "./components/AuthCard.jsx";
import { ChatRoom } from "./components/ChatRoom.jsx";
import { useChatSocket } from "./hooks/useChatSocket.js";
import { useHealth } from "./hooks/useHealth.js";
import {
  DEFAULT_ROOMS,
  DEFAULT_WEBSOCKET_PORT,
  MAX_MESSAGE_LENGTH,
} from "./lib/protocol.js";

export default function App() {
  // The token lives in memory only, so closing the tab ends the session and no
  // other script on the machine can read it out of storage.
  const [session, setSession] = useState(null);
  const [room, setRoom] = useState(DEFAULT_ROOMS[0]);
  const [notice, setNotice] = useState("");
  const { health, error: healthError, refresh: refreshHealth } = useHealth();

  const rooms = useMemo(() => {
    const names = health?.rooms ? Object.keys(health.rooms) : [];
    return names.length > 0 ? names : DEFAULT_ROOMS;
  }, [health]);

  const websocketPort = Number.isInteger(health?.websocket_port)
    ? health.websocket_port
    : DEFAULT_WEBSOCKET_PORT;
  // Set only when the server runs behind a TLS proxy that forwards this path.
  const websocketPath = health?.websocket_path ?? null;
  // The server owns this limit, so follow whatever it reports.
  const maxMessageLength = Number.isInteger(health?.max_message_length)
    ? health.max_message_length
    : MAX_MESSAGE_LENGTH;

  const handleSessionExpired = useCallback((message) => {
    window.setTimeout(() => {
      setSession(null);
      setNotice(message);
    }, 1200);
  }, []);

  const { messages, status, statusText, sendMessage, reconnect } = useChatSocket({
    token: session?.token ?? null,
    username: session?.username ?? "",
    room,
    websocketPort,
    websocketPath,
    maxMessageLength,
    onSessionExpired: handleSessionExpired,
  });

  useEffect(() => {
    document.title = session ? `TSPO Chat - ${room}` : "TSPO Chat";
  }, [session, room]);

  function handleAuthenticated(next) {
    setNotice("");
    setRoom(next.room);
    setSession({ token: next.token, username: next.username });
  }

  function handleSelectRoom(nextRoom) {
    // Each room needs its own connection, so the transcript restarts as well.
    if (nextRoom !== room) {
      setRoom(nextRoom);
    }
  }

  function handleLeave() {
    setSession(null);
    setNotice("");
    refreshHealth();
  }

  if (!session) {
    return (
      <AuthCard
        rooms={rooms}
        health={health}
        healthError={healthError}
        notice={notice}
        onAuthenticated={handleAuthenticated}
      />
    );
  }

  return (
    <ChatRoom
      username={session.username}
      room={room}
      rooms={rooms}
      status={status}
      statusText={statusText}
      messages={messages}
      maxMessageLength={maxMessageLength}
      onSelectRoom={handleSelectRoom}
      onSend={sendMessage}
      onReconnect={reconnect}
      onLeave={handleLeave}
    />
  );
}
