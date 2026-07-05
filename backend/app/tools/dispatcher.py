from __future__ import annotations

from typing import Any

from browser_agent_contracts import ActionCall
from langchain_core.messages import ToolMessage
from langgraph.types import interrupt

from app.agent.state import AgentState
from app.browser.base import BrowserSession
from app.events.emitter import EventEmitter

# tool-call name -> ActionCall name
_BROWSER_ACTION = {
    "Navigate": "navigate",
    "Click": "click",
    "LongPress": "long_press",
    "TypeText": "type",
    "Scroll": "scroll",
    "Extract": "extract",
    "SearchPage": "search_page",
    "FindElements": "find_elements",
    "WaitFor": "wait_for",
    "PressKey": "press_key",
    "Clear": "clear",
    "SelectOption": "select_option",
    "NewTab": "new_tab",
    "SwitchTab": "switch_tab",
    "CloseTab": "close_tab",
    "ObserveTab": "observe_tab",
    "OpenInNewTab": "open_in_new_tab",
}


class ToolDispatcher:
    """Turns one structured tool call into an effect + a ToolMessage + a state delta."""

    async def dispatch(
        self,
        tool_call: dict[str, Any],
        *,
        state: AgentState,
        session: BrowserSession,
        emitter: EventEmitter,
    ) -> tuple[ToolMessage, dict[str, Any]]:
        name = tool_call["name"]
        args = tool_call.get("args", {}) or {}
        call_id = tool_call["id"]
        await emitter.emit_tool_call(name, args)

        if name in _BROWSER_ACTION:
            call = ActionCall(name=_BROWSER_ACTION[name], args=args)
            result = await session.act(call)
            content = result.reason or ("ok" if result.success else "failed")
            return (
                ToolMessage(content=content, tool_call_id=call_id, name=name),
                {"last_action": call, "last_result": result},
            )

        if name == "Remember":
            merged = {**state.agent_memory, args["key"]: args["value"]}
            await emitter.emit_memory(args["key"])
            return (
                ToolMessage(content=f"Remembered: {args['key']}", tool_call_id=call_id, name=name),
                {"agent_memory": merged},
            )

        if name == "Recall":
            text = "\n".join(f"- {k}: {v}" for k, v in state.agent_memory.items()) or "(empty)"
            return ToolMessage(content=text, tool_call_id=call_id, name=name), {}

        if name == "SetPlan":
            steps = list(args.get("steps", []))
            await emitter.emit_plan(steps)
            return (
                ToolMessage(content=f"Plan set ({len(steps)} steps)", tool_call_id=call_id, name=name),
                {},
            )

        if name == "AskUser":
            answer = interrupt({"question": args["question"], "context": args.get("context", "")})
            return (
                ToolMessage(content=f"User answered: {answer}", tool_call_id=call_id, name=name),
                {},
            )

        if name == "Complete":
            return (
                ToolMessage(content="Task marked complete", tool_call_id=call_id, name=name),
                {"finished": True, "success": bool(args["success"]), "reason": args.get("reason", "")},
            )

        return ToolMessage(content=f"Unknown tool: {name}", tool_call_id=call_id, name=name), {}
