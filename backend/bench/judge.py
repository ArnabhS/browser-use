"""LLM judge for benchmark runs — a faithful port of browser-use's judge (gemini-2.5-flash, binary
verdict) so our scores are comparable to their leaderboard. Called over OpenRouter with our own key
(used only in the Authorization header, never logged)."""
from __future__ import annotations

import json
import re

import httpx

from app.config.settings import get_settings

JUDGE_MODEL = "google/gemini-2.5-flash"
_URL = "https://openrouter.ai/api/v1/chat/completions"

_SYSTEM = """You are an expert judge evaluating browser automation agent performance.

<evaluation_framework>
**PRIMARY EVALUATION CRITERIA (in order of importance):**
1. **Task Satisfaction (Most Important)**: Did the agent accomplish what the user asked for? Break the task into key criteria and evaluate whether the agent met all of them. Focus on user intent and final outcome.
2. **Output Quality**: Is the final result in the correct format and complete? Does it match exactly what was requested?
3. **Tool Effectiveness**: Did the browser interactions work as expected?
4. **Agent Reasoning**: Quality of decision-making and problem-solving throughout the trajectory.
5. **Browser Handling**: Navigation stability and error recovery. If the browser crashes, does not load, or a captcha blocks the task, the score must be very low.

**VERDICT GUIDELINES:**
- true: Task completed as requested, all of the user's criteria met, and the agent did not make up any information.
- false: Task not completed, or only partially completed.

Examples: if a task asks for 10 items and the agent finds 4 correctly -> false. If completed to full requirements with minor trajectory errors -> true. If impossible due to captcha/login -> false. If the agent reports an action complete but the screenshot shows otherwise -> false. If the agent made up content not in the page -> false.

**FAILURE CONDITIONS (automatically false):** blocked by captcha or missing auth; output format wrong or missing; infinite loops/severe technical failure; critical requirements ignored; page not loaded; browser crashed; could not interact with required UI; moved past an important step without completing it; fabricated content; called done before completing all key points.

**IMPORTANT NOTES:**
- The agent has the entire DOM, but a screenshot is only part of the content — if the agent extracts info you can't see in the screenshot, assume it is there.
- Be very picky: hold a high standard for completing the task exactly to the user's request, and be initially doubtful of the agent's self-reported success.
</evaluation_framework>

Respond with EXACTLY this JSON structure (no text before or after):
{"reasoning": "...", "verdict": true or false, "failure_reason": "...", "impossible_task": true or false, "reached_captcha": true or false}
"""


def _dedupe_last(shots: list[str], n: int) -> list[str]:
    seen: set[str] = set()
    unique = [s for s in reversed(shots) if not (s in seen or seen.add(s))]
    return list(reversed(unique[:n]))


async def judge(task: str, final_result: str, steps_text: str, shots_b64: list[str],
                *, max_images: int = 8, timeout: float = 120.0) -> dict:
    """Return the parsed verdict dict ({verdict: bool, ...}); on any failure, verdict False + error."""
    images = [{"type": "image_url", "image_url": {"url": f"data:image/png;base64,{s}"}}
              for s in _dedupe_last(shots_b64, max_images)]
    user_text = (
        f"<task>\n{task[:40000]}\n</task>\n\n"
        f"<agent_trajectory>\n{steps_text[:40000] or 'No trajectory'}\n</agent_trajectory>\n\n"
        f"<final_result>\n{final_result[:40000] or 'No final result'}\n</final_result>\n\n"
        f"{len(images)} screenshots from execution are attached. "
        "Evaluate and respond with the exact JSON structure requested."
    )
    payload = {
        "model": JUDGE_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": [{"type": "text", "text": user_text}, *images]},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0,
    }
    key = get_settings().openrouter_api_key
    # Retry once: a transient error or a non-JSON reply shouldn't silently score the task a failure.
    last_err = "no response"
    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(_URL, headers={"Authorization": f"Bearer {key}"}, json=payload)
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
            parsed = _parse(content)
            if parsed is not None:
                return parsed
            last_err = "unparseable judge output"
        except Exception as exc:
            last_err = f"judge error: {exc}"
    return {"verdict": False, "reasoning": "", "failure_reason": last_err,
            "impossible_task": False, "reached_captcha": False}


def _parse(content: str) -> dict | None:
    """Parse the judge JSON, tolerating code fences and prose around it. None → unparseable (retry)."""
    text = content.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1].removeprefix("json").strip()
    candidates = [text]
    match = re.search(r"\{.*\"verdict\".*\}", text, re.DOTALL)
    if match:
        candidates.append(match.group(0))
    for cand in candidates:
        try:
            data = json.loads(cand)
        except Exception:
            continue
        data["verdict"] = bool(data.get("verdict", False))
        return data
    return None
