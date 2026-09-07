import { Brand } from "./Brand.jsx";
import { Composer } from "./Composer.jsx";
import { MessageList } from "./MessageList.jsx";
import { RoomTabs } from "./RoomTabs.jsx";
import { StatusDot } from "./StatusDot.jsx";

const GHOST_BUTTON =
  "rounded-lg border border-plum-200 px-3 py-1.5 text-sm text-plum-500 transition " +
  "hover:text-plum-800 dark:border-plum-800 dark:text-plum-300 dark:hover:text-plum-50";

export function ChatRoom({
  username,
  room,
  rooms,
  status,
  statusText,
  messages,
  maxMessageLength,
  onSelectRoom,
  onSend,
  onReconnect,
  onLeave,
}) {
  const online = status === "online";

  return (
    <div className="mx-auto grid h-dvh max-w-4xl grid-rows-[auto_1fr_auto] border-plum-200 bg-white sm:border-x dark:border-plum-800 dark:bg-plum-850">
      <header className="flex flex-wrap items-center gap-x-4 gap-y-3 border-b border-plum-200 px-4 py-3 dark:border-plum-800">
        <div className="flex min-w-0 items-center gap-2.5">
          <Brand compact />
          <div className="min-w-0">
            <strong className="block truncate">{room}</strong>
            <span className="text-xs text-plum-500 dark:text-plum-300">
              signed in as <span className="font-semibold text-plum-800 dark:text-plum-50">{username}</span>
            </span>
          </div>
        </div>

        <div className="order-3 w-full sm:order-none sm:ms-auto sm:w-auto">
          <RoomTabs rooms={rooms} activeRoom={room} disabled={!online} onSelect={onSelectRoom} />
        </div>

        <div className="ms-auto flex items-center gap-2.5 sm:ms-0">
          <span className="flex items-center gap-2 text-sm text-plum-500 dark:text-plum-300">
            <StatusDot tone={status} />
            {statusText}
          </span>
          {!online && status !== "connecting" && (
            <button type="button" onClick={onReconnect} className={GHOST_BUTTON}>
              Reconnect
            </button>
          )}
          <button type="button" onClick={onLeave} className={GHOST_BUTTON}>
            Leave
          </button>
        </div>
      </header>

      <MessageList messages={messages} username={username} />
      <Composer disabled={!online} maxLength={maxMessageLength} onSend={onSend} />
    </div>
  );
}
