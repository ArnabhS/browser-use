import { useEffect, useRef } from "react";
import { PROTOCOL_VERSION } from "@browser-agent/contracts";
import { useAgentRun } from "./lib/useAgentRun";
import { Header } from "./cockpit/Header";
import { Composer } from "./cockpit/Composer";
import { Transcript } from "./cockpit/Transcript";
import { Viewport } from "./cockpit/Viewport";

const EXAMPLES = [
  "Open YouTube, search lofi hip hop, and play the first video",
  "Go to Wikipedia and give me the first paragraph of the Apollo 11 article",
];

function EmptyState({ onRun }: { onRun: (task: string) => void }) {
  return (
    <div className="flex h-full flex-col items-center justify-center text-center">
      <div className="mb-5 grid h-12 w-14 place-items-center rounded-lg border border-line2 bg-raised2">
        <span className="node-live h-2.5 w-2.5 rounded-full bg-accent" />
      </div>
      <h1 className="font-display text-2xl font-semibold tracking-tight text-text">
        Watch the agent work
      </h1>
      <p className="mt-2 max-w-md text-[15px] leading-relaxed text-muted">
        Describe a task. The agent reads the page, reasons step by step, and drives a real
        browser — you'll see every thought as it happens.
      </p>
      <div className="mt-7 flex w-full max-w-md flex-col gap-2">
        {EXAMPLES.map((ex) => (
          <button
            key={ex}
            onClick={() => onRun(ex)}
            className="group rounded-xl border border-line bg-raised px-4 py-3 text-left text-sm text-muted transition-colors hover:border-line2 hover:text-text"
          >
            <span className="mr-2 font-mono text-accentdim group-hover:text-accent">→</span>
            {ex}
          </button>
        ))}
      </div>
    </div>
  );
}

export default function App() {
  const { status, task, timeline, streaming, question, result, error, frame, pageUrl, start, answer, stop } =
    useAgentRun();
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [timeline, streaming, question, result, error]);

  const showEmpty = status === "idle" && !task;

  return (
    <div className="flex h-full flex-col">
      <Header status={status} version={PROTOCOL_VERSION} />
      {showEmpty ? (
        <main className="scroll-area flex-1 overflow-y-auto">
          <div className="mx-auto h-full max-w-[46rem] px-5 py-8">
            <EmptyState onRun={start} />
          </div>
        </main>
      ) : (
        <main className="flex min-h-0 flex-1 flex-col gap-4 p-4 lg:flex-row">
          {/* live browser view — the streaming panel */}
          <section className="min-h-0 basis-1/2 lg:basis-3/5">
            <Viewport frame={frame} pageUrl={pageUrl} status={status} />
          </section>
          {/* reasoning + action step log */}
          <section className="scroll-area min-h-0 flex-1 overflow-y-auto lg:basis-2/5">
            <div className="mx-auto max-w-[44rem] px-1 py-1">
              <Transcript
                task={task}
                timeline={timeline}
                streaming={streaming}
                question={question}
                result={result}
                status={status}
                onAnswer={answer}
              />
              {error && (
                <div className="rise mt-4 rounded-xl border border-warn/40 bg-warn/[0.07] px-4 py-3">
                  <div className="font-display text-sm font-semibold text-warn">Can't continue</div>
                  <p className="mt-1 whitespace-pre-wrap break-words font-mono text-[13px] leading-relaxed text-muted">
                    {error}
                  </p>
                </div>
              )}
              <div ref={bottomRef} />
            </div>
          </section>
        </main>
      )}
      <Composer status={status} onRun={start} onStop={stop} />
    </div>
  );
}
