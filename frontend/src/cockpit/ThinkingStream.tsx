import { useEffect, useRef } from "react";
import type { TimelineItem } from "../lib/types";

interface ThinkingStreamProps {
  timeline: TimelineItem[];
  streaming: string;
}

function ActionChip({ name, args }: { name: string; args: Record<string, unknown> }) {
  let argsStr: string;
  try {
    argsStr = JSON.stringify(args);
  } catch {
    argsStr = "{}";
  }
  return (
    <div className="flex items-start gap-2 my-2">
      <span className="text-indigo-400 font-mono text-xs mt-0.5 shrink-0">→</span>
      <code className="font-mono text-xs bg-zinc-800 text-indigo-300 border border-zinc-700 rounded px-2 py-1 break-all">
        {name}({argsStr})
      </code>
    </div>
  );
}

function ThoughtBlock({ text }: { text: string }) {
  return (
    <div className="my-2 text-sm text-zinc-400 leading-relaxed whitespace-pre-wrap border-l-2 border-zinc-700 pl-3">
      {text}
    </div>
  );
}

export function ThinkingStream({ timeline, streaming }: ThinkingStreamProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [timeline, streaming]);

  const isEmpty = timeline.length === 0 && !streaming;

  return (
    <div className="flex-1 overflow-y-auto px-4 py-4">
      {isEmpty ? (
        <p className="text-zinc-600 text-sm italic text-center mt-16">
          Agent thinking will appear here…
        </p>
      ) : (
        <>
          {timeline.map((item, i) =>
            item.kind === "thought" ? (
              <ThoughtBlock key={i} text={item.text} />
            ) : (
              <ActionChip key={i} name={item.name} args={item.args} />
            )
          )}
          {streaming && (
            <div className="my-2 text-sm text-zinc-300 leading-relaxed whitespace-pre-wrap border-l-2 border-indigo-600 pl-3">
              {streaming}
              <span className="inline-block w-[2px] h-[1em] bg-indigo-400 ml-0.5 align-text-bottom animate-[blink_1s_step-start_infinite]" />
            </div>
          )}
        </>
      )}
      <div ref={bottomRef} />
    </div>
  );
}
