import type { RunStatus } from "../lib/types";

const LABEL: Record<RunStatus, string> = {
  idle: "Ready",
  running: "Thinking",
  waiting_for_user: "Needs you",
  stopping: "Stopping",
  stopped: "Stopped",
  done: "Done",
  error: "Error",
};

const DOT: Record<RunStatus, string> = {
  idle: "bg-faint",
  running: "bg-accent",
  waiting_for_user: "bg-warn",
  stopping: "bg-muted",
  stopped: "bg-muted",
  done: "bg-ok",
  error: "bg-warn",
};

export function Header({ status, version }: { status: RunStatus; version: string }) {
  return (
    <header className="flex h-14 shrink-0 items-center justify-between border-b border-line px-5">
      <div className="flex items-center gap-2.5">
        <span className="grid h-6 w-7 place-items-center rounded-[5px] border border-line2 bg-raised2">
          <span className="h-1.5 w-1.5 rounded-full bg-accent" />
        </span>
        <span className="font-display font-semibold tracking-tight">Browser Use</span>
        <span className="text-sm text-faint">cockpit</span>
      </div>
      <div className="flex items-center gap-2.5">
        <span className={`h-2 w-2 rounded-full ${DOT[status]} ${status === "running" ? "node-live" : ""}`} />
        <span className="font-mono text-sm text-muted">{LABEL[status]}</span>
        <span className="ml-2 font-mono text-xs text-faint">v{version}</span>
      </div>
    </header>
  );
}
