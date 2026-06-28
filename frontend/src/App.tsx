import { PROTOCOL_VERSION } from "@browser-agent/contracts";
import { useAgentRun } from "./lib/useAgentRun";
import { TaskBar } from "./cockpit/TaskBar";
import { ThinkingStream } from "./cockpit/ThinkingStream";
import { AskUserPanel } from "./cockpit/AskUserPanel";
import { StatusBar } from "./cockpit/StatusBar";

export default function App() {
  const { status, timeline, streaming, question, result, error, start, answer } = useAgentRun();

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 flex flex-col">
      {/* Title bar */}
      <header className="flex items-center justify-between px-5 py-3 border-b border-zinc-800 shrink-0">
        <span className="text-sm font-semibold tracking-wide text-zinc-100">
          Browser Agent · Cockpit
        </span>
        <span className="text-xs text-zinc-600 font-mono">v{PROTOCOL_VERSION}</span>
      </header>

      {/* Status bar */}
      <div className="shrink-0 border-b border-zinc-800/60">
        <StatusBar status={status} result={result} error={error} />
      </div>

      {/* Task input */}
      <div className="shrink-0 p-4 border-b border-zinc-800/60">
        <TaskBar status={status} onStart={start} />
      </div>

      {/* Main thinking stream — scrolls independently */}
      <ThinkingStream timeline={timeline} streaming={streaming} />

      {/* AskUser panel — sits above the bottom when active */}
      {question && <AskUserPanel question={question} onAnswer={answer} />}
    </div>
  );
}
