# agent/tools/browser_tool.py
from dataclasses import dataclass
from typing import Any, Dict, Optional

from playwright.async_api import async_playwright, Page


@dataclass
class PageState:
    url: str
    dom_snapshot: str  # 原始 HTML
    ready: bool = True


class BrowserTool:
    def __init__(self):
        self._state = PageState(url="about:blank", dom_snapshot="", ready=True)
        self._playwright = None
        self._browser = None
        self._page: Optional[Page] = None

    async def _ensure_page(self) -> Page:
        if self._page is not None:
            return self._page

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=True)
        self._page = await self._browser.new_page()
        return self._page

    async def goto(self, url: str) -> PageState:
        page = await self._ensure_page()
        # await page.goto(url, wait_until="domcontentloaded", timeout=10000)
        await page.goto(url, wait_until="networkidle", timeout=10000)

        self._state.url = page.url
        self._state.dom_snapshot = await page.content()
        # ⭐ 等待 arXiv 搜索结果渲染（如果是搜索页）
        try:
            await page.wait_for_selector("li.arxiv-result", timeout=5000)
        except Exception:
            pass

        return self._state

    async def click(self, selector: str) -> PageState:
        page = await self._ensure_page()
        await page.click(selector, timeout=5000)
        self._state.url = page.url
        self._state.dom_snapshot = await page.content()
        # ⭐ 等待 arXiv 搜索结果渲染（如果是搜索页）
        try:
            await page.wait_for_selector("li.arxiv-result", timeout=5000)
        except Exception:
            pass

        return self._state

    async def type(self, selector: str, text: str, clear: bool = True) -> PageState:
        page = await self._ensure_page()
        if clear:
            await page.fill(selector, text, timeout=5000)
        else:
            await page.type(selector, text, timeout=5000)
        self._state.url = page.url
        self._state.dom_snapshot = await page.content()
        return self._state

    async def scroll(self, direction: str = "down", amount: int = 1000) -> PageState:
        page = await self._ensure_page()
        dy = amount if direction == "down" else -amount
        await page.mouse.wheel(0, dy)
        self._state.url = page.url
        self._state.dom_snapshot = await page.content()
                # ⭐ 等待 arXiv 搜索结果渲染（如果是搜索页）
        try:
            await page.wait_for_selector("li.arxiv-result", timeout=5000)
        except Exception:
            pass

        return self._state

    async def press(self, key: str) -> PageState:
        page = await self._ensure_page()
        await page.keyboard.press(key)
        self._state.url = page.url
        self._state.dom_snapshot = await page.content()
                # ⭐ 等待 arXiv 搜索结果渲染（如果是搜索页）
        try:
            await page.wait_for_selector("li.arxiv-result", timeout=5000)
        except Exception:
            pass

        return self._state

    async def wait_dom_stable(self, timeout: float = 2000) -> PageState:
        page = await self._ensure_page()
        await page.wait_for_timeout(timeout)
        self._state.url = page.url
        self._state.dom_snapshot = await page.content()
        return self._state

    async def screenshot(self) -> bytes:
        page = await self._ensure_page()
        return await page.screenshot(full_page=True)

    async def get_dom_summary(self) -> Dict[str, Any]:
        page = await self._ensure_page()

        # 基础信息
        url = page.url
        try:
            title = await page.title()
        except Exception:  # noqa: BLE001
            title = ""

        # 抽取可交互元素（简化版，数量做限制防止 prompt 过长）
        summary: Dict[str, Any] = {
            "url": url,
            "title": title,
            "inputs": [],
            "buttons": [],
            "links": [],
        }

        try:
            # 输入框：重点保留可能是搜索框的
            inputs = await page.query_selector_all("input")
            for idx, el in enumerate(inputs):
                if idx >= 10:
                    break
                try:
                    itype = await el.get_attribute("type") or "text"
                    placeholder = await el.get_attribute("placeholder") or ""
                    name = await el.get_attribute("name") or ""
                    aria = await el.get_attribute("aria-label") or ""
                    summary["inputs"].append(
                        {
                            "index": idx,
                            "type": itype,
                            "name": name,
                            "placeholder": placeholder,
                            "aria_label": aria,
                        }
                    )
                except Exception:
                    continue

            # 按钮
            buttons = await page.query_selector_all("button")
            for idx, el in enumerate(buttons):
                if idx >= 10:
                    break
                try:
                    text = (await el.inner_text()).strip()[:80]
                    summary["buttons"].append({"index": idx, "text": text})
                except Exception:
                    continue

            # 链接（只保留前 30 个有文本的）
            links = await page.query_selector_all("a[href]")
            for idx, el in enumerate(links):
                if len(summary["links"]) >= 30:
                    break
                try:
                    text = (await el.inner_text()).strip()
                    href = await el.get_attribute("href")
                    if text and href:
                        summary["links"].append(
                            {
                                "index": len(summary["links"]),
                                "text": text[:80],
                                "href": href,
                            }
                        )
                except Exception:
                    continue
        except Exception:
            # 如果提取失败，至少返回截断 HTML
            pass

        # 仍然附带一小段原始 HTML，方便模型理解上下文
        summary["html_snippet"] = self._state.dom_snapshot[:2000]
        return summary

    async def close(self) -> None:
        if self._browser is not None:
            await self._browser.close()
        if self._playwright is not None:
            await self._playwright.stop()
