import { cx } from "../lib/cx.js";

export function RoomTabs({ rooms, activeRoom, disabled, onSelect }) {
  return (
    <nav aria-label="Rooms" className="flex flex-wrap gap-1.5">
      {rooms.map((room) => {
        const isActive = room === activeRoom;
        return (
          <button
            key={room}
            type="button"
            disabled={disabled}
            aria-current={isActive ? "true" : "false"}
            onClick={() => onSelect(room)}
            className={cx(
              "rounded-full border px-3 py-1.5 text-sm transition",
              "disabled:cursor-not-allowed disabled:opacity-55",
              isActive
                ? "border-magenta-500 bg-magenta-500 font-semibold text-white"
                : "border-plum-200 text-plum-500 hover:text-plum-800 dark:border-plum-800 dark:text-plum-300 dark:hover:text-plum-50",
            )}
          >
            {room}
          </button>
        );
      })}
    </nav>
  );
}
