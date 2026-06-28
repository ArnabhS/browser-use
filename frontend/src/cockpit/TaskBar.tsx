import { useState } from "react";
import type { RunStatus } from "../lib/types";

interface TaskBarProps {
  status: RunStatus;
  onStart: (task: string) => void;
}

export function TaskBar({ status, onStart }: TaskBarProps) {
  const [task, setTask] = useState("");

  const isBlocked = status === "running" || status === "waiting_for_user";

  const handleRun = () => {
    const trimmed = task.trim();
    if (trimmed && !isBlocked) {
      onStart(trimmed);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      handleRun();
    }
  };

  return (
    <div className="flex gap-3 p-4 bg-zinc-900 border border-zinc-800 rounded-xl">
      <textarea
        className="flex-1 resize-none bg-zinc-800 text-zinc-100 placeholder-zinc-500 rounded-lg px-4 py-3 text-sm leading-relaxed focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-0 disabled:opacity-50 min-h-[80px]"
        placeholder="Describe a task for the agent… (Cmd+Enter to run)"
        value={task}
        onChange={(e) => setTask(e.target.value)}
        onKeyDown={handleKeyDown}
        disabled={isBlocked}
        rows={3}
      />
      <button
        onClick={handleRun}
        disabled={isBlocked || !task.trim()}
        className="self-end px-5 py-2.5 bg-indigo-600 hover:bg-indigo-500 disabled:bg-zinc-700 disabled:text-zinc-500 text-white text-sm font-medium rounded-lg transition-colors focus:outline-none focus:ring-2 focus:ring-indigo-500 whitespace-nowrap"
      >
        {isBlocked ? "Running…" : "Run"}
      </button>
    </div>
  );
}
