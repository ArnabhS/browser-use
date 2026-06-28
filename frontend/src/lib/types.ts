export type AgentEvent = { event: string; data: Record<string, unknown>; ts: string };

export type TimelineItem =
  | { kind: "thought"; text: string }
  | { kind: "action"; name: string; args: Record<string, unknown> };

export type RunStatus =
  | "idle"
  | "running"
  | "waiting_for_user"
  | "stopping"
  | "stopped"
  | "done"
  | "error";
