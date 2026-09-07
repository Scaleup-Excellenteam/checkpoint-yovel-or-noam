import { useEffect, useRef, useState } from "react";

import { cx } from "../lib/cx.js";
import { CONTROL_CHARACTERS, MAX_MESSAGE_LENGTH } from "../lib/protocol.js";

export function Composer({ disabled, onSend }) {
  const [draft, setDraft] = useState("");
  const textareaRef = useRef(null);

  // Grow the textarea with its content, up to a fixed ceiling.
  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = "auto";
    textarea.style.height = `${Math.min(textarea.scrollHeight, 140)}px`;
  }, [draft]);

  useEffect(() => {
    if (!disabled) {
      textareaRef.current?.focus();
    }
  }, [disabled]);

  const trimmed = draft.trim();
  const canSend = !disabled && trimmed.length > 0 && draft.length <= MAX_MESSAGE_LENGTH;

  function handleSubmit(event) {
    event.preventDefault();
    if (!canSend) return;
    if (onSend(trimmed)) {
      setDraft("");
    }
  }

  function handleKeyDown(event) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      handleSubmit(event);
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="flex items-end gap-3 border-t border-plum-200 bg-white px-4 py-3 dark:border-plum-800 dark:bg-plum-850"
    >
      <label htmlFor="message-input" className="sr-only">
        Message
      </label>
      <textarea
        id="message-input"
        ref={textareaRef}
        rows={1}
        value={draft}
        disabled={disabled}
        maxLength={MAX_MESSAGE_LENGTH}
        autoComplete="off"
        placeholder={disabled ? "Not connected" : "Write a message and press Enter..."}
        onKeyDown={handleKeyDown}
        // The server rejects control characters, so they never reach the wire.
        onChange={(event) => setDraft(event.target.value.replace(CONTROL_CHARACTERS, " "))}
        className="max-h-36 w-full resize-none rounded-xl border border-plum-200 bg-white px-3 py-2.5 placeholder:text-plum-300 disabled:opacity-60 dark:border-plum-800 dark:bg-plum-900 dark:placeholder:text-plum-500"
      />
      <div className="grid shrink-0 justify-items-end gap-1.5">
        <span
          className={cx(
            "text-xs tabular-nums",
            draft.length >= MAX_MESSAGE_LENGTH ? "font-semibold text-rose-600" : "text-plum-400",
          )}
        >
          {draft.length}/{MAX_MESSAGE_LENGTH}
        </span>
        <button
          type="submit"
          disabled={!canSend}
          className="rounded-xl bg-magenta-500 px-5 py-2.5 font-semibold text-white transition hover:bg-magenta-600 disabled:cursor-not-allowed disabled:opacity-50"
        >
          Send
        </button>
      </div>
    </form>
  );
}
