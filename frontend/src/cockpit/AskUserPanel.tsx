import { useState } from "react";
import type { Question } from "../lib/useAgentRun";

interface AskUserPanelProps {
  question: Question;
  onAnswer: (text: string) => void;
}

export function AskUserPanel({ question, onAnswer }: AskUserPanelProps) {
  const [reply, setReply] = useState("");

  const handleSend = () => {
    const trimmed = reply.trim();
    if (trimmed) {
      onAnswer(trimmed);
      setReply("");
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      handleSend();
    }
  };

  return (
    <div className="mx-4 mb-4 bg-amber-950/60 border border-amber-600/50 rounded-xl p-4 shadow-lg">
      <div className="flex items-start gap-2 mb-2">
        <span className="text-amber-400 text-base shrink-0">⊙</span>
        <p className="text-amber-100 text-sm font-medium leading-snug">{question.question}</p>
      </div>
      {question.context && (
        <p className="text-amber-300/70 text-xs mb-3 pl-6 leading-relaxed">{question.context}</p>
      )}
      <div className="flex gap-2 pl-6">
        <input
          autoFocus
          type="text"
          value={reply}
          onChange={(e) => setReply(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Your answer…"
          className="flex-1 bg-zinc-800 border border-zinc-700 text-zinc-100 placeholder-zinc-500 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-amber-500"
        />
        <button
          onClick={handleSend}
          disabled={!reply.trim()}
          className="px-4 py-2 bg-amber-600 hover:bg-amber-500 disabled:bg-zinc-700 disabled:text-zinc-500 text-white text-sm font-medium rounded-lg transition-colors focus:outline-none focus:ring-2 focus:ring-amber-500"
        >
          Send
        </button>
      </div>
    </div>
  );
}
