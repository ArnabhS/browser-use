import { memo } from "react";
import type { RunStatus } from "../lib/types";

const LIVE: RunStatus[] = ["running", "waiting_for_user", "stopping"];

/** Live browser panel: a continuous CDP screencast of the page the agent is driving, painted
 *  frame-by-frame into an <img>. Memoized so only new frames re-render it, not the step log. */
export const Viewport = memo(function Viewport({
  frame,
  pageUrl,
  status,
}: {
  frame: string | null;
  pageUrl: string | null;
  status: RunStatus;
}) {
  const live = LIVE.includes(status);
  return (
    <div className="flex h-full flex-col overflow-hidden rounded-xl border border-line bg-ink">
      <div className="flex items-center gap-2 border-b border-line bg-raised px-3 py-2">
        <span className={`h-2 w-2 rounded-full ${live ? "node-live bg-warn" : "bg-faint"}`} />
        <span className="font-mono text-[10px] uppercase tracking-wider text-faint">
          {live ? "Live" : "Browser"}
        </span>
        <span className="ml-1 min-w-0 flex-1 truncate font-mono text-[12px] text-muted">
          {pageUrl ?? ""}
        </span>
      </div>
      <div className="relative flex min-h-0 flex-1 items-center justify-center bg-black/40">
        {frame ? (
          <img
            src={frame}
            alt="Live browser view"
            className="max-h-full max-w-full object-contain"
          />
        ) : (
          <div className="text-center">
            <div className="node-live mx-auto mb-3 h-2.5 w-2.5 rounded-full bg-accent" />
            <p className="text-sm text-muted">Waiting for the browser…</p>
          </div>
        )}
      </div>
    </div>
  );
});
