# agent/planner.py
from dataclasses import dataclass
from typing import Any, Dict, Literal

ActionType = Literal["goto", "click", "type", "scroll", "press",
                     "download", "final_answer", "retry", "error"]


@dataclass
class AgentAction:
    type: ActionType
    params: Dict[str, Any]


@dataclass
class PlannerInput:
    task: str
    history: list[Dict[str, Any]]
    dom_summary: Dict[str, Any] | None = None
    screenshot_path: str | None = None
    current_url: str | None = None


class Planner:
    """调用 VLLM 模型，根据页面信息和任务决定下一步动作。"""

    def __init__(self, model: Any):
        # model: models/ 下的任意 *VLLM 实例，需实现 analyze()
        self.model = model
        self.last_urls = []   # ⭐新增：跟踪最近数次 URL

    async def plan_next(self, inp: PlannerInput) -> AgentAction:
        """PLAN / ANALYSIS 阶段：调用大模型返回动作 JSON。"""

        # === 模型生成动作 ===
        model_result = self.model.analyze(
            screenshot_path=inp.screenshot_path,
            dom_summary=str(inp.dom_summary or ""),
            user_goal=inp.task,
            current_url=inp.current_url or "",
        )

        action_str = str(model_result.get("action", "")).upper().strip()
        param = str(model_result.get("parameter", "")).strip()

        valid_actions = {"GOTO", "CLICK", "TYPE", "SCROLL", "DONE"}

        # === ⭐ 1. URL 自动稳定检测逻辑 ===
        curr_url = inp.current_url or ""
        self.last_urls.append(curr_url)

        # 只保留最近 3 条
        if len(self.last_urls) > 3:
            self.last_urls.pop(0)

        # 如果最近3次 URL 都一样 → 模型毫无进展 → 自动 DONE
        if len(set(self.last_urls)) == 1 and len(inp.history) > 2:
            return AgentAction(
                type="final_answer",
                params={
                    "answer": model_result, 
                    "auto_done": True,
                    "reason": "URL did not change for 3 steps"
                },
            )

        # === 2. 第一轮禁止 DONE ===
        is_first_step = len(inp.history) == 0
        if is_first_step and action_str == "DONE":
            if param.startswith("http://") or param.startswith("https://"):
                action_str = "GOTO"
            else:
                return AgentAction(
                    type="final_answer",
                    params={"answer": model_result, "error": "first_step_done_without_url"},
                )

        # === 3. 非法动作 ===
        if action_str not in valid_actions:
            return AgentAction(
                type="final_answer",
                params={"answer": model_result, "error": "invalid_action"},
            )

        # === 4. 模型主动 DONE ===
        if action_str == "DONE":
            return AgentAction(
                type="final_answer",
                params={"answer": model_result}
            )

        # === 5. 执行动作 ===
        if action_str == "GOTO":
            if not (param.startswith("http://") or param.startswith("https://")):
                return AgentAction(type="final_answer",
                                params={"answer": model_result, "error": "invalid_url"})
            return AgentAction(type="goto", params={"url": param})

        if action_str == "CLICK":
            if not param:
                return AgentAction(type="final_answer",
                                params={"answer": model_result, "error": "empty_selector"})
            return AgentAction(type="click", params={"selector": param})

        if action_str == "TYPE":
            if ":::" in param:
                sel, txt = param.split(":::", 1)
            else:
                sel, txt = "input", param
            return AgentAction(type="type", params={"selector": sel, "text": txt})

        if action_str == "SCROLL":
            direction = param.lower() if param.lower() in {"up", "down"} else "down"
            return AgentAction(type="scroll", params={"direction": direction})

        return AgentAction(type="final_answer",
                        params={"answer": model_result, "error": "unreachable"})

