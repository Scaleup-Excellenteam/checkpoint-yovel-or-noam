import { cx } from "../lib/cx.js";

const TONES = {
  online: "bg-emerald-500",
  connecting: "bg-amber-500 animate-pulse",
  offline: "bg-rose-500",
  blocked: "bg-rose-500",
  unknown: "bg-plum-400",
};

export function StatusDot({ tone = "unknown", className }) {
  return (
    <span
      aria-hidden="true"
      className={cx("inline-block size-2.5 shrink-0 rounded-full", TONES[tone] ?? TONES.unknown, className)}
    />
  );
}
