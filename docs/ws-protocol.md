# Cockpit WebSocket Protocol (v1 — thinking-stream + ask-user slice)

The browser cockpit talks to the backend over a single WebSocket. Scope of this version:
stream the agent's **reasoning ("thinking")** and handle the **AskUser** human-in-the-loop.
Execution streaming (screenshots, full step log) is **out of scope** here.

## Endpoint

```
ws://localhost:8000/ws/run
```

One run per connection lifecycle is fine, but the connection MAY stay open and accept a new
`start` after a run completes. While a run is active, `answer` messages are routed to it.

## Client → Server (JSON text frames)

```jsonc
{ "type": "start",  "task": "<the task text>", "thread_id": "<optional, server defaults one>" }
{ "type": "answer", "answer": "<the user's reply to an AskUser question>" }
```

## Server → Client (JSON text frames)

Every agent event is forwarded verbatim as the backend `AgentEvent`:

```jsonc
{ "event": "<type>", "data": { ... }, "ts": "<UTC ISO-8601>" }
```

Event types the cockpit cares about in this slice:

| `event`          | `data`                          | Cockpit use |
|------------------|----------------------------------|-------------|
| `status`         | `{ phase, message }`             | top status line |
| `stream`         | `{ token }`                      | **live thinking** — append tokens as they arrive (typewriter) |
| `reasoning`      | `{ text }`                       | finalized reasoning block for the turn (replaces/confirms the streamed buffer) |
| `tool_call`      | `{ name, args }`                 | one line: "→ name(args)" (the action it chose) |
| `question`       | `{ question, context }`          | **show an answer input**; user reply is sent back as `{type:"answer"}` |
| `usage`          | `{ inputTokens, outputTokens, ... }` | optional small meter |
| `context_status` | `{ input_tokens, ... }`          | optional |
| `error`          | `{ message }`                    | show an error |
| `finalize`       | `{ success, reason }`            | the agent finished (success/fail + why) |
| `run_complete`   | `{ success?, reason? }`          | **server sentinel** sent after the run task returns; the stream for this run has ended |

Notes:
- `stream` and `reasoning` carry the same content — `stream` is the per-token delta during
  generation; `reasoning` is the full text emitted once when the turn's LLM call returns. A simple
  cockpit can accumulate `stream` tokens into the current "thinking" bubble and, on the next
  `tool_call`/`reasoning`, freeze it as a completed thought.
- The think-before-act retry can produce a second burst of `stream` tokens within one turn.

## AskUser flow

1. Agent calls `AskUser` → graph interrupts → server emits `{ "event": "question", "data": {question, context} }`.
2. Cockpit renders the question + an input; nothing else streams until answered.
3. User submits → cockpit sends `{ "type": "answer", "answer": "<text>" }`.
4. Server resumes the graph with that answer; streaming continues.

## Lifecycle / errors

- On `start`, the server builds a fresh agent (its own browser session + event sink bound to this
  socket) and runs it; events stream as they happen.
- When the run task finishes, the server sends `run_complete` (so the client doesn't rely solely on
  `finalize`, which may be absent on some failure paths).
- If the socket disconnects mid-run, the server cancels the run and tears down the browser session.
- Malformed / unknown client messages are ignored (optionally a `status` warning).
