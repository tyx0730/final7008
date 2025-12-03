# agent/controller.py
from __future__ import annotations

import asyncio
from typing import Any, Dict

from .config import AgentConfig
from .fsm import FSM, FSMContext, State
from .logger import log_event
from .planner import Planner, PlannerInput
from .storage import Storage
from .tools.browser_tool import BrowserTool
from .tools.file_tool import FileTool
from .tools.ocr_tool import OcrTool

class AgentController:
    def __init__(self, cfg: AgentConfig | None = None, planner: Planner | None = None):
        self.cfg = cfg or AgentConfig()
        self.fsm = FSM()
        # planner 由外部注入（携带具体 VLLM 模型）；如未提供则占位
        self.planner = planner if planner is not None else None
        self.storage = Storage(self.cfg)
        self.browser = BrowserTool()
        self.file_tool = FileTool()
        self.ocr_tool = OcrTool()

    async def run(self, task: str, max_steps: int | None = None) -> Dict[str, Any]:
        ctx = FSMContext(task=task)
        ctx.state = State.PLAN
        step_idx = 0

        while ctx.state != State.DONE:
            step_idx += 1
            if max_steps is not None and step_idx > max_steps:
                ctx.result = ctx.result or {"answer": "max_steps reached", "steps": ctx.history}
                break
            log_event("STATE", {"state": ctx.state.name})

            if ctx.state in {State.PLAN, State.ANALYSIS}:
                planner_in = PlannerInput(
                    task=ctx.task,
                    history=ctx.history,
                    dom_summary=ctx.history[-1].get("dom") if ctx.history else None,
                    screenshot_path=ctx.history[-1].get("screenshot_path") if ctx.history else None,
                    current_url=self.browser._state.url if self.browser else "",
                )
                action = await self.planner.plan_next(planner_in)
                ctx.last_action = {"step": step_idx, "type": action.type, "params": action.params}
                ctx.history.append({"state": ctx.state.name, "action": ctx.last_action})
                ctx.state = self.fsm.next_state_from_action(ctx.state, action.type)
                if action.type == "final_answer":
                    ctx.result = action.params
                continue

            # 浏览器/工具操作
            if ctx.state == State.GOTO:
                try:
                    page_state = await self.browser.goto(ctx.last_action["params"]["url"])
                    ctx.history.append({"step": step_idx, "event": "goto", "url": page_state.url})
                    ctx.state = self.fsm.next_state_from_action(ctx.state, "nav_done")
                except Exception as e:  # noqa: BLE001
                    err = str(e)
                    ctx.history.append({"step": step_idx, "event": "goto_error", "error": err})
                    ctx.result = {"answer": "browser_error", "error": err, "steps": ctx.history}
                    ctx.state = State.SAVE_OUTPUT
                continue

            if ctx.state == State.CLICK:
                selector = ctx.last_action["params"]["selector"]
                try:
                    page_state = await self.browser.click(selector)
                    ctx.history.append({"step": step_idx, "event": "click", "selector": selector, "url": page_state.url})
                    ctx.state = self.fsm.next_state_from_action(ctx.state, "click_done")
                except Exception as e:  # noqa: BLE001
                    err = str(e)
                    ctx.history.append({"step": step_idx, "event": "click_error", "selector": selector, "error": err})
                    ctx.result = {"answer": "browser_error", "error": err, "steps": ctx.history}
                    ctx.state = State.SAVE_OUTPUT
                continue

            if ctx.state == State.TYPE:
                p = ctx.last_action["params"]
                try:
                    page_state = await self.browser.type(p["selector"], p["text"])
                    ctx.history.append({"step": step_idx, "event": "type", "selector": p["selector"], "text": p["text"], "url": page_state.url})
                    ctx.state = self.fsm.next_state_from_action(ctx.state, "type_done")
                except Exception as e:  # noqa: BLE001
                    err = str(e)
                    ctx.history.append({"step": step_idx, "event": "type_error", "selector": p["selector"], "error": err})
                    ctx.result = {"answer": "browser_error", "error": err, "steps": ctx.history}
                    ctx.state = State.SAVE_OUTPUT
                continue

            if ctx.state == State.SCROLL:
                try:
                    page_state = await self.browser.scroll()
                    ctx.history.append({"step": step_idx, "event": "scroll", "url": page_state.url})
                    ctx.state = self.fsm.next_state_from_action(ctx.state, "scroll_done")
                except Exception as e:  # noqa: BLE001
                    err = str(e)
                    ctx.history.append({"step": step_idx, "event": "scroll_error", "error": err})
                    ctx.result = {"answer": "browser_error", "error": err, "steps": ctx.history}
                    ctx.state = State.SAVE_OUTPUT
                continue

            if ctx.state == State.PRESS:
                key = ctx.last_action["params"]["key"]
                try:
                    page_state = await self.browser.press(key)
                    ctx.history.append({"step": step_idx, "event": "press", "key": key, "url": page_state.url})
                    ctx.state = self.fsm.next_state_from_action(ctx.state, "press_done")
                except Exception as e:  # noqa: BLE001
                    err = str(e)
                    ctx.history.append({"step": step_idx, "event": "press_error", "key": key, "error": err})
                    ctx.result = {"answer": "browser_error", "error": err, "steps": ctx.history}
                    ctx.state = State.SAVE_OUTPUT
                continue

            if ctx.state == State.DOWNLOAD:
                url = ctx.last_action["params"]["url"]
                res = await self.file_tool.download(url)
                if res.success:
                    pdf_text = await self.file_tool.parse_pdf(res.path)
                    ctx.history.append({"event": "pdf_parsed", "text": pdf_text})
                    ctx.state = State.PDF_PROCESS
                else:
                    ctx.state = State.ERROR
                continue

            if ctx.state == State.WAIT_DOM:
                # print("DEBUG: wait_dom_stable returned:", page_state)
                try:
                    page_state = await self.browser.wait_dom_stable()
                    ctx.history.append({"step": step_idx, "event": "wait_dom", "url": page_state.url})
                    ctx.state = self.fsm.next_state_from_action(ctx.state, "dom_ready")
                except Exception as e:  # noqa: BLE001
                    err = str(e)
                    ctx.history.append({"step": step_idx, "event": "wait_dom_error", "error": err})
                    ctx.result = {"answer": "browser_error", "error": err, "steps": ctx.history}
                    ctx.state = State.SAVE_OUTPUT
                continue

            if ctx.state == State.SCREENSHOT:
                try:
                    img_bytes = await self.browser.screenshot()
                    path = self.storage.save_screenshot(img_bytes, step_id=f"step{step_idx}")
                    ctx.history.append({"step": step_idx, "event": "screenshot", "screenshot_path": path})
                    log_event("SCREENSHOT_SAVED", {"step": step_idx, "path": path})
                    ctx.state = self.fsm.next_state_from_action(ctx.state, "shot_done")
                except Exception as e:  # noqa: BLE001
                    err = str(e)
                    ctx.history.append({"step": step_idx, "event": "screenshot_error", "error": err})
                    ctx.result = {"answer": "browser_error", "error": err, "steps": ctx.history}
                    ctx.state = State.SAVE_OUTPUT
                continue

            if ctx.state == State.DOM_SUMMARY:
                dom = await self.browser.get_dom_summary()
                self.storage.save_dom_summary(dom, step_id=f"step{step_idx}")
                ctx.history.append({"step": step_idx, "event": "dom_summary", "dom": dom})
                ctx.state = self.fsm.next_state_from_action(ctx.state, "dom_done")
                continue

            if ctx.state == State.PDF_PROCESS:
                ctx.state = self.fsm.next_state_from_action(ctx.state, "pdf_done")
                continue

            if ctx.state == State.RETRY:
                ctx.state = self.fsm.next_state_from_action(ctx.state, "retry")
                continue

            if ctx.state == State.ERROR:
                ctx.state = self.fsm.next_state_from_action(ctx.state, "error")
                continue

            if ctx.state == State.SAVE_OUTPUT:
                if ctx.result is None:
                    ctx.result = {"answer": "no result", "steps": ctx.history}
                path = self.storage.save_final_output(ctx.result)
                ctx.history.append({"step": step_idx, "event": "saved_output", "path": path})
                ctx.state = State.DONE
                continue

        return ctx.result or {"answer": "no result", "steps": ctx.history}

# 供直接运行测试：
async def _demo():
    controller = AgentController()
    res = await controller.run("示例任务：打开网页并给出总结")
    print("Final result:", res)

if __name__ == "__main__":
    asyncio.run(_demo())