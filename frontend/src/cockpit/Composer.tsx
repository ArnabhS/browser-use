import { useState } from "react";
import type { RunStatus } from "../lib/types";

const BUSY: RunStatus[] = ["running", "waiting_for_user", "stopping"];

export function Composer({
  status,
  onRun,
  onStop,
}: {
  status: RunStatus;
  onRun: (task: string) => void;
  onStop: () => void;
}) {
  const [value, setValue] = useState("");
  const busy = BUSY.includes(status);
  const stopping = status === "stopping";

  const submit = () => {
    const t = value.trim();
    if (!t || busy) return;
    onRun(t);
  };

  return (
    <div>
      <div className="flex items-end gap-2 rounded-2xl border border-line2 bg-raised2 p-2 pl-4 transition-colors focus-within:border-accentdim">
        <textarea
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
              e.preventDefault();
              submit();
            }
          }}
          rows={1}
          placeholder="Give the agent a task…"
          disabled={busy}
          className="max-h-40 flex-1 resize-none bg-transparent py-2 text-[15px] leading-relaxed text-text outline-none placeholder:text-faint disabled:opacity-50"
        />
        {busy ? (
          <button
            onClick={onStop}
            disabled={stopping}
            className="flex h-10 shrink-0 items-center gap-2 rounded-xl bg-warn/15 px-4 font-display text-sm font-medium text-warn transition-colors hover:bg-warn/25 disabled:opacity-50"
          >
            <span className="h-2.5 w-2.5 rounded-[3px] bg-warn" />
            {stopping ? "Stopping…" : "Stop"}
          </button>
        ) : (
          <button
            onClick={submit}
            disabled={!value.trim()}
            className="h-10 shrink-0 rounded-xl bg-accent px-5 font-display text-sm font-semibold text-ink transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40"
          >
            Run
          </button>
        )}
      </div>
      <p className="mt-2 font-mono text-[11px] text-faint">⌘↵ to run · drives a real browser</p>
    </div>
  );
}
