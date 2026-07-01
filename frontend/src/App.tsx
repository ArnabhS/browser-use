import { useEffect, useRef } from "react";
import { PROTOCOL_VERSION } from "@browser-agent/contracts";
import { useAgentRun } from "./lib/useAgentRun";
import { Header } from "./cockpit/Header";
import { Composer } from "./cockpit/Composer";
import { Transcript } from "./cockpit/Transcript";
import { Viewport } from "./cockpit/Viewport";

const EXAMPLES = [
  "Open Flipkart, search hats, sort price low to high, add the first to cart",
  "Go to Wikipedia and give me the first paragraph of the Apollo 11 article",
];

function Hero({ onRun }: { onRun: (task: string) => void }) {
  return (
    <div>
      <div className="font-mono text-[11px] uppercase tracking-[0.22em] text-accentdim">
        Autonomous browser agent
      </div>
      <h1 className="mt-3 font-display text-[2rem] font-semibold leading-[1.08] tracking-tight text-text">
        Give it a task.
        <br />
        Watch it drive the browser.
      </h1>
      <p className="mt-3 max-w-lg text-[15px] leading-relaxed text-muted">
        It reads the page, reasons one step at a time, and acts in a real browser — every thought and
        click streamed to you live.
      </p>
      <div className="mt-7">
        <div className="mb-2 font-mono text-[11px] uppercase tracking-wider text-faint">Try one</div>
        <div className="flex flex-col gap-2">
          {EXAMPLES.map((ex) => (
            <button
              key={ex}
              onClick={() => onRun(ex)}
              className="group flex items-start gap-3 rounded-xl border border-line bg-raised px-4 py-3 text-left text-sm leading-relaxed text-muted transition-colors hover:border-line2 hover:bg-raised2 hover:text-text"
            >
              <span className="mt-0.5 font-mono text-accentdim transition-colors group-hover:text-accent">
                →
              </span>
              <span>{ex}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

export default function App() {
  const { status, task, timeline, streaming, question, result, error, waking, hasFrame, pageUrl, subscribeFrame, start, answer, stop } =
    useAgentRun();
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [timeline, streaming, question, result, error]);

  const showEmpty = status === "idle" && !task;

  return (
    <div className="flex h-full flex-col">
      <Header status={status} version={PROTOCOL_VERSION} waking={waking} />

      {showEmpty ? (
        <main className="scroll-area flex-1 overflow-y-auto">
          <div className="mx-auto flex min-h-full w-full max-w-[40rem] flex-col justify-center px-6 py-12">
            <Hero onRun={start} />
            <div className="mt-8">
              <Composer status={status} onRun={start} onStop={stop} />
            </div>
          </div>
        </main>
      ) : (
        <main className="flex min-h-0 flex-1 flex-col gap-3 p-3 lg:flex-row lg:gap-4 lg:p-4">
          {/* live browser — top on mobile, hero on the right on desktop */}
          <section className="h-[38vh] min-h-0 shrink-0 lg:order-2 lg:h-auto lg:flex-1">
            <Viewport
              subscribeFrame={subscribeFrame}
              pageUrl={pageUrl}
              status={status}
              hasFrame={hasFrame}
            />
          </section>

          {/* conversation rail — task → timeline → composer as one continuous column */}
          <section className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl border border-line bg-raised/30 lg:order-1 lg:w-[27rem] lg:flex-none">
            <div className="scroll-area min-h-0 flex-1 overflow-y-auto px-5 pt-5">
              <Transcript
                task={task}
                timeline={timeline}
                streaming={streaming}
                question={question}
                result={result}
                status={status}
                waking={waking}
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
            <div className="shrink-0 border-t border-line bg-ink/50 px-5 pb-4 pt-3">
              <Composer status={status} onRun={start} onStop={stop} />
            </div>
          </section>
        </main>
      )}
    </div>
  );
}
