import { cx } from "../lib/cx.js";

export function Brand({ compact = false }) {
  return (
    <span
      aria-hidden="true"
      className={cx(
        "grid place-items-center rounded-xl bg-plum-100 dark:bg-plum-800",
        compact ? "size-9 text-lg" : "size-12 text-2xl",
      )}
    >
      🍕
    </span>
  );
}
