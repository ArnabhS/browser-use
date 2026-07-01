import { useCallback, useEffect, useRef, useState } from "react";
import type { AgentEvent, RunStatus, TimelineItem } from "./types";

export interface Question {
  question: string;
  context?: string;
}

export interface RunResult {
  success: boolean;
  reason: string;
  stopped?: boolean;
}

export interface AgentRunState {
  status: RunStatus;
  task: string;
  timeline: TimelineItem[];
  streaming: string;
  question: Question | null;
  result: RunResult | null;
  error: string | null;
  frame: string | null;
  pageUrl: string | null;
  start: (task: string) => void;
  answer: (text: string) => void;
  stop: () => void;
}

const WS_URL = (import.meta.env.VITE_WS_URL as string | undefined) ?? "ws://localhost:8000/ws/run";
const BUSY: RunStatus[] = ["running", "waiting_for_user", "stopping"];

export function useAgentRun(): AgentRunState {
  const [status, setStatus] = useState<RunStatus>("idle");
  const [task, setTask] = useState<string>("");
  const [timeline, setTimeline] = useState<TimelineItem[]>([]);
  const [streaming, setStreaming] = useState<string>("");
  const [question, setQuestion] = useState<Question | null>(null);
  const [result, setResult] = useState<RunResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [frame, setFrame] = useState<string | null>(null);
  const [pageUrl, setPageUrl] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
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

  const flushStreaming = useCallback(() => {
    if (streamingRef.current.trim()) {
      const text = streamingRef.current;
      setTimeline((prev) => [...prev, { kind: "thought", text }]);
    }
    streamingRef.current = "";
    setStreaming("");
  }, []);

  const start = useCallback(
    (taskText: string) => {
      closeSocket();
      setStatus("running");
      setTask(taskText);
      setTimeline([]);
      setStreaming("");
      streamingRef.current = "";
      setQuestion(null);
      setResult(null);
      setError(null);
      setFrame(null);
      setPageUrl(null);

      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;

      ws.onopen = () => ws.send(JSON.stringify({ type: "start", task: taskText }));

      ws.onerror = () => {
        setError(
          `Can't reach the agent at ${WS_URL}. Is the backend running? ` +
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

        if (event === "frame") {
          const b64 = data.data as string | undefined;
          if (b64) setFrame(`data:image/jpeg;base64,${b64}`);
          if (typeof data.url === "string") setPageUrl(data.url);
        } else if (event === "observation") {
          if (typeof data.url === "string") setPageUrl(data.url as string);
        } else if (event === "stream") {
          streamingRef.current += (data.token as string | undefined) ?? "";
          setStreaming(streamingRef.current);
        } else if (event === "reasoning") {
          streamingRef.current = (data.text as string | undefined) ?? "";
          setStreaming(streamingRef.current);
        } else if (event === "tool_call") {
          flushStreaming();
          setTimeline((prev) => [
            ...prev,
            {
              kind: "action",
              name: (data.name as string | undefined) ?? "",
              args: (data.args as Record<string, unknown> | undefined) ?? {},
            },
          ]);
        } else if (event === "question") {
          flushStreaming();
          setQuestion({
            question: (data.question as string | undefined) ?? "",
            context: data.context as string | undefined,
          });
          setStatus("waiting_for_user");
        } else if (event === "finalize") {
          setResult({
            success: Boolean(data.success),
            reason: (data.reason as string | undefined) ?? "",
          });
        } else if (event === "error") {
          setError((data.message as string | undefined) ?? "Something went wrong.");
          setStatus("error");
        } else if (event === "run_complete") {
          flushStreaming();
          const stopped = Boolean(data.stopped);
          if (stopped) {
            setResult({
              success: false,
              stopped: true,
              reason: (data.reason as string | undefined) ?? "Stopped by you.",
            });
          }
          setStatus((prev) => (prev === "error" ? "error" : stopped ? "stopped" : "done"));
          closeSocket();
        }
      };

      ws.onclose = () => {
        setStatus((prev) => (BUSY.includes(prev) ? "done" : prev));
      };
    },
    [closeSocket, flushStreaming]
  );

  const answer = useCallback(
    (text: string) => {
      send({ type: "answer", answer: text });
      setQuestion(null);
      setStatus("running");
    },
    [send]
  );

  const stop = useCallback(() => {
    send({ type: "stop" });
    setQuestion(null);
    setStatus("stopping");
  }, [send]);

  useEffect(() => () => closeSocket(), [closeSocket]);

  return { status, task, timeline, streaming, question, result, error, frame, pageUrl, start, answer, stop };
}
