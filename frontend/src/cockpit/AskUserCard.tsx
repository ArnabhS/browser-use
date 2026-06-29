import { useState } from "react";
import type { Question } from "../lib/useAgentRun";

export function AskUserCard({
  question,
  onAnswer,
}: {
  question: Question;
  onAnswer: (text: string) => void;
}) {
  const [value, setValue] = useState("");

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const t = value.trim();
    if (t) onAnswer(t);
  };

  return (
    <div className="relative rise border-l border-line pb-5 pl-7">
      <span className="node-live absolute -left-[6px] top-[6px] h-[11px] w-[11px] rounded-full bg-accent" />
      <div className="rounded-xl border border-accentdim/50 bg-accent/[0.06] px-4 py-3.5">
        <div className="mb-1.5 font-mono text-[11px] uppercase tracking-wider text-accent">
          Agent needs you
        </div>
        <p className="text-[15px] leading-relaxed text-text">{question.question}</p>
        {question.context && <p className="mt-1 text-sm text-muted">{question.context}</p>}
        <form onSubmit={submit} className="mt-3 flex gap-2">
          <input
            value={value}
            onChange={(e) => setValue(e.target.value)}
            autoFocus
            placeholder="Type your answer…"
            className="h-10 flex-1 rounded-lg border border-line2 bg-ink px-3 text-sm text-text outline-none transition-colors placeholder:text-faint focus:border-accentdim"
          />
          <button
            type="submit"
            disabled={!value.trim()}
            className="h-10 shrink-0 rounded-lg bg-accent px-4 font-display text-sm font-semibold text-ink transition hover:brightness-110 disabled:opacity-40"
          >
            Send
          </button>
        </form>
      </div>
    </div>
  );
}
