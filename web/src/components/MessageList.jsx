import { useEffect, useRef } from "react";

import { cx } from "../lib/cx.js";

const SYSTEM_TONES = {
  info: "bg-indigo-50 text-indigo-800 dark:bg-indigo-950/70 dark:text-indigo-200",
  success: "bg-emerald-50 text-emerald-800 dark:bg-emerald-950/70 dark:text-emerald-200",
  error: "bg-rose-50 text-rose-700 dark:bg-rose-950/70 dark:text-rose-200",
};

const formatTime = (date) =>
  date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

function SystemNotice({ text, tone }) {
  return (
    <li className={cx("self-center max-w-[90%] rounded-full px-4 py-1.5 text-center text-sm", SYSTEM_TONES[tone] ?? SYSTEM_TONES.info)}>
      {text}
    </li>
  );
}

function ChatBubble({ sender, text, at, isOwn }) {
  return (
    <li className={cx("flex max-w-[85%] gap-2.5 sm:max-w-[70%]", isOwn && "flex-row-reverse self-end")}>
      <span
        aria-hidden="true"
        className={cx(
          "grid size-8 shrink-0 place-items-center rounded-full text-xs font-bold uppercase text-white",
          isOwn ? "bg-magenta-500" : "bg-plum-600",
        )}
      >
        {sender.slice(0, 2)}
      </span>
      <div
        className={cx(
          "min-w-0 rounded-2xl px-3 py-2",
          isOwn ? "bg-magenta-500 text-white" : "bg-plum-100 dark:bg-plum-800",
        )}
      >
        <p className="flex items-baseline gap-2 text-xs">
          <span className={cx("font-bold", isOwn ? "text-white/85" : "text-plum-600 dark:text-magenta-300")}>
            {isOwn ? "You" : sender}
          </span>
          <span className={cx("tabular-nums", isOwn ? "text-white/70" : "text-plum-400")}>{formatTime(at)}</span>
        </p>
        <p className="wrap-anywhere">{text}</p>
      </div>
    </li>
  );
}

export function MessageList({ messages, username }) {
  const listRef = useRef(null);
  const pinnedRef = useRef(true);

  function handleScroll(event) {
    const { scrollHeight, scrollTop, clientHeight } = event.currentTarget;
    pinnedRef.current = scrollHeight - scrollTop - clientHeight < 80;
  }

  useEffect(() => {
    if (pinnedRef.current && listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, [messages]);

  return (
    <ol
      ref={listRef}
      onScroll={handleScroll}
      aria-live="polite"
      aria-relevant="additions"
      tabIndex={0}
      className="flex flex-col gap-2.5 overflow-y-auto bg-plum-50 px-4 py-5 dark:bg-plum-950"
    >
      {messages.map((message) =>
        message.kind === "chat" ? (
          <ChatBubble
            key={message.id}
            sender={message.sender}
            text={message.text}
            at={message.at}
            isOwn={message.sender === username}
          />
        ) : (
          <SystemNotice key={message.id} text={message.text} tone={message.tone} />
        ),
      )}
    </ol>
  );
}
