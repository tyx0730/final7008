# agent/fsm.py
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Any, Dict, Optional

from .logger import log_event

class State(Enum):
    START = auto()
    PLAN = auto()
    GOTO = auto()
    CLICK = auto()
    TYPE = auto()
    SCROLL = auto()
    PRESS = auto()
    WAIT_DOM = auto()
    SCREENSHOT = auto()
    DOM_SUMMARY = auto()
    ANALYSIS = auto()
    DOWNLOAD = auto()
    PDF_PROCESS = auto()
    RETRY = auto()
    ERROR = auto()
    SAVE_OUTPUT = auto()
    DONE = auto()

@dataclass
class FSMContext:
    task: str
    state: State = State.START
    history: list[Dict[str, Any]] = None
    last_action: Optional[Dict[str, Any]] = None
    result: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if self.history is None:
            self.history = []

class FSM:
    def __init__(self):
        ...

    def next_state_from_action(self, current: State, action_type: str) -> State:
        log_event("FSM_TRANSITION", {"from": current.name, "action": action_type})

        if current in {State.START, State.PLAN, State.ANALYSIS}:
            if action_type == "goto":
                return State.GOTO
            if action_type == "click":
                return State.CLICK
            if action_type == "type":
                return State.TYPE
            if action_type == "scroll":
                return State.SCROLL
            if action_type == "press":
                return State.PRESS
            if action_type == "download":
                return State.DOWNLOAD
            if action_type == "final_answer":
                return State.SAVE_OUTPUT
            if action_type == "retry":
                return State.RETRY
            if action_type == "error":
                return State.ERROR

        # if current in {State.GOTO, State.CLICK, State.TYPE, State.SCROLL, State.PRESS, State.DOWNLOAD}:
        #     return State.WAIT_DOM
        if current in {State.GOTO, State.CLICK, State.TYPE, State.SCROLL, State.PRESS, State.DOWNLOAD}:
            # Actions that finish browser ops
            if action_type in {
                "nav_done", "click_done", "type_done",
                "scroll_done", "press_done"
            }:
                return State.WAIT_DOM

        if current == State.WAIT_DOM:
            # WAIT_DOM -> SCREENSHOT + DOM_SUMMARY -> ANALYSIS
            return State.SCREENSHOT

        if current == State.SCREENSHOT:
            return State.DOM_SUMMARY

        if current in {State.DOM_SUMMARY, State.PDF_PROCESS, State.RETRY}:
            return State.ANALYSIS

        if current == State.SAVE_OUTPUT:
            return State.DONE

        if current == State.ERROR:
            # 简化：直接 SAVE_OUTPUT
            return State.SAVE_OUTPUT

        return State.ERROR