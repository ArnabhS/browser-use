import { useCallback, useEffect, useRef, useState } from "react";
import type { AgentEvent, RunStatus, TimelineItem } from "./types";

export interface Question {
  question: string;
  context?: string;
}

export interface RunResult {
  success: boolean;
  reason: string;
}

export interface AgentRunState {
  status: RunStatus;
  timeline: TimelineItem[];
  streaming: string;
  question: Question | null;
  result: RunResult | null;
  error: string | null;
  start: (task: string) => void;
  answer: (text: string) => void;
}

const WS_URL = (import.meta.env.VITE_WS_URL as string | undefined) ?? "ws://localhost:8000/ws/run";

export function useAgentRun(): AgentRunState {
  const [status, setStatus] = useState<RunStatus>("idle");
  const [timeline, setTimeline] = useState<TimelineItem[]>([]);
  const [streaming, setStreaming] = useState<string>("");
  const [question, setQuestion] = useState<Question | null>(null);
  const [result, setResult] = useState<RunResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  // Keep streaming in a ref so event handlers always see the current value
  const streamingRef = useRef<string>("");

  const closeSocket = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.onmessage = null;
      wsRef.current.onerror = null;
      wsRef.current.onclose = null;
      wsRef.current.close();
      wsRef.current = null;
    }
  }, []);

  const send = useCallback((payload: object) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(payload));
    }
  }, []);

  const start = useCallback(
    (task: string) => {
      closeSocket();

      // Reset all state
      setStatus("running");
      setTimeline([]);
      setStreaming("");
      streamingRef.current = "";
      setQuestion(null);
      setResult(null);
      setError(null);

      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;

      ws.onopen = () => {
        ws.send(JSON.stringify({ type: "start", task }));
      };

      ws.onerror = () => {
        setError(
          `Can't reach the backend at ${WS_URL}. Is it running? ` +
            `Start it with:  cd backend && uv run uvicorn app.api.main:app --port 8000`
        );
        setStatus("error");
        closeSocket();
      };

      ws.onmessage = (evt: MessageEvent<string>) => {
        let parsed: AgentEvent;
        try {
          parsed = JSON.parse(evt.data) as AgentEvent;
        } catch {
          return;
        }

        const { event, data } = parsed;

        if (event === "stream") {
          const token = (data.token as string | undefined) ?? "";
          streamingRef.current += token;
          setStreaming(streamingRef.current);
        } else if (event === "reasoning") {
          const text = (data.text as string | undefined) ?? "";
          streamingRef.current = text;
          setStreaming(text);
        } else if (event === "tool_call") {
          const name = (data.name as string | undefined) ?? "";
          const args = (data.args as Record<string, unknown> | undefined) ?? {};
          // Flush current streaming buffer as a thought first
          if (streamingRef.current.trim()) {
            const capturedText = streamingRef.current;
            setTimeline((prev) => [...prev, { kind: "thought", text: capturedText }]);
            streamingRef.current = "";
            setStreaming("");
          }
          setTimeline((prev) => [...prev, { kind: "action", name, args }]);
        } else if (event === "question") {
          const q = (data.question as string | undefined) ?? "";
          const ctx = data.context as string | undefined;
          setQuestion({ question: q, context: ctx });
          setStatus("waiting_for_user");
        } else if (event === "finalize") {
          const success = Boolean(data.success);
          const reason = (data.reason as string | undefined) ?? "";
          setResult({ success, reason });
        } else if (event === "error") {
          const message = (data.message as string | undefined) ?? "Unknown error";
          setError(message);
          setStatus("error");
        } else if (event === "run_complete") {
          // Flush any remaining streaming content
          if (streamingRef.current.trim()) {
            const capturedText = streamingRef.current;
            setTimeline((prev) => [...prev, { kind: "thought", text: capturedText }]);
            streamingRef.current = "";
            setStreaming("");
          }
          setStatus((prev) => (prev === "error" ? "error" : "done"));
          closeSocket();
        }
        // Ignore: status, usage, context_status, observation
      };

      ws.onclose = () => {
        // If we closed unexpectedly (not via run_complete), treat as done
        setStatus((prev) => (prev === "running" || prev === "waiting_for_user" ? "done" : prev));
      };
    },
    [closeSocket]
  );

  const answer = useCallback(
    (text: string) => {
      send({ type: "answer", answer: text });
      setQuestion(null);
      setStatus("running");
    },
    [send]
  );

  // Clean up on unmount
  useEffect(() => {
    return () => {
      closeSocket();
    };
  }, [closeSocket]);

  return { status, timeline, streaming, question, result, error, start, answer };
}
