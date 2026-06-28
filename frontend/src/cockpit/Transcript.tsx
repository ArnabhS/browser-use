import type { RunStatus, TimelineItem } from "../lib/types";
import type { Question, RunResult } from "../lib/useAgentRun";
import { AskUserCard } from "./AskUserCard";

function fmtArgs(args: Record<string, unknown>): string {
  return Object.entries(args)
    .map(([k, v]) => (typeof v === "string" ? v : `${k}=${JSON.stringify(v)}`))
    .join(", ");
}

function ThoughtRow({ text, live }: { text: string; live?: boolean }) {
  return (
    <div className="rise relative border-l border-line pb-4 pl-7">
      <span
        className={`absolute -left-[5px] top-[7px] h-[9px] w-[9px] rounded-full ${
          live ? "node-live bg-accent" : "bg-accentdim"
        }`}
      />
      <p className={`text-[15px] leading-relaxed text-text/90 ${live ? "cursor" : ""}`}>{text}</p>
    </div>
  );
}

function ActionRow({ name, args }: { name: string; args: Record<string, unknown> }) {
  const a = fmtArgs(args);
  return (
    <div className="rise relative border-l border-line pb-4 pl-7">
      <span className="absolute -left-[5px] top-[7px] h-[9px] w-[9px] rounded-full border-2 border-accentdim bg-ink" />
      <div className="font-mono text-[13px]">
        <span className="text-accent">→ </span>
        <span className="text-text">{name}</span>
        {a && <span className="text-faint"> {a}</span>}
      </div>
    </div>
  );
}

function ResultBanner({ result }: { result: RunResult }) {
  const kind = result.stopped ? "stopped" : result.success ? "ok" : "fail";
  const node = kind === "ok" ? "bg-ok" : kind === "fail" ? "bg-warn" : "bg-muted";
  const title = kind === "ok" ? "Done" : kind === "fail" ? "Couldn't finish" : "Stopped";
  const titleColor = kind === "ok" ? "text-ok" : kind === "fail" ? "text-warn" : "text-muted";
  return (
    <div className="rise relative border-l border-line pl-7 pt-1">
      <span className={`absolute -left-[6px] top-[5px] h-[11px] w-[11px] rounded-full ${node}`} />
      <div className="rounded-xl border border-line bg-raised px-4 py-3">
        <div className={`font-display text-sm font-semibold ${titleColor}`}>{title}</div>
        <p className="mt-1 text-sm leading-relaxed text-muted">{result.reason}</p>
      </div>
    </div>
  );
}

export function Transcript({
  task,
  timeline,
  streaming,
  question,
  result,
  status,
  onAnswer,
}: {
  task: string;
  timeline: TimelineItem[];
  streaming: string;
  question: Question | null;
  result: RunResult | null;
  status: RunStatus;
  onAnswer: (text: string) => void;
}) {
  const warming = status === "running" && timeline.length === 0 && !streaming;

  return (
    <div>
      <div className="mb-6">
        <div className="mb-1 font-mono text-[11px] uppercase tracking-wider text-faint">Task</div>
        <p className="font-display text-lg leading-snug text-text">{task}</p>
      </div>

      <div>
        {timeline.map((item, i) =>
          item.kind === "thought" ? (
            <ThoughtRow key={i} text={item.text} />
          ) : (
            <ActionRow key={i} name={item.name} args={item.args} />
          )
        )}
        {streaming && <ThoughtRow text={streaming} live />}
        {warming && (
          <div className="rise relative border-l border-line pb-4 pl-7">
            <span className="node-live absolute -left-[5px] top-[7px] h-[9px] w-[9px] rounded-full bg-accent" />
            <p className="text-[15px] text-muted">Opening the browser…</p>
          </div>
        )}
        {question && <AskUserCard question={question} onAnswer={onAnswer} />}
        {result && <ResultBanner result={result} />}
      </div>
    </div>
  );
}
