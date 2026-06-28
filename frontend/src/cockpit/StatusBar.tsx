import type { RunStatus } from "../lib/types";
import type { RunResult } from "../lib/useAgentRun";

interface StatusBarProps {
  status: RunStatus;
  result: RunResult | null;
  error: string | null;
}

const STATUS_LABELS: Record<RunStatus, string> = {
  idle: "Idle",
  running: "Running",
  waiting_for_user: "Waiting for you",
  done: "Done",
  error: "Error",
};

const STATUS_CLASSES: Record<RunStatus, string> = {
  idle: "bg-zinc-800 text-zinc-400",
  running: "bg-indigo-900/60 text-indigo-300 border border-indigo-700/50",
  waiting_for_user: "bg-amber-900/60 text-amber-300 border border-amber-700/50",
  done: "bg-emerald-900/60 text-emerald-300 border border-emerald-700/50",
  error: "bg-red-900/60 text-red-300 border border-red-700/50",
};

export function StatusBar({ status, result, error }: StatusBarProps) {
  return (
    <div className="flex items-center gap-3 px-4 py-2 flex-wrap">
      <span className={`text-xs font-medium px-2.5 py-1 rounded-full ${STATUS_CLASSES[status]}`}>
        {status === "running" && (
          <span className="inline-block w-1.5 h-1.5 rounded-full bg-indigo-400 mr-1.5 animate-pulse align-middle" />
        )}
        {STATUS_LABELS[status]}
      </span>

      {status === "done" && result && (
        <div
          className={`flex items-center gap-1.5 text-xs rounded-lg px-3 py-1 ${
            result.success
              ? "bg-emerald-900/40 text-emerald-300 border border-emerald-800/50"
              : "bg-red-900/40 text-red-300 border border-red-800/50"
          }`}
        >
          <span>{result.success ? "✓" : "✗"}</span>
          <span>{result.reason}</span>
        </div>
      )}

      {status === "error" && error && (
        <div className="flex items-center gap-1.5 text-xs rounded-lg px-3 py-1 bg-red-900/40 text-red-300 border border-red-800/50">
          <span>✗</span>
          <span>{error}</span>
        </div>
      )}
    </div>
  );
}
