import asyncio
from copy import deepcopy
import datetime
import io
import os
import time
from typing import Dict, List, Literal, Optional, Tuple, Union, cast

import urllib
from playwright.async_api import async_playwright
from PIL import Image, ImageDraw, ImageFont
from html2text import html2text


def update_page_after_click(func):
    async def wrapper(self, *args, **kwargs):
        new_page_future = asyncio.ensure_future(
            self.page.context.wait_for_event("page", timeout=3000)
        )

        result = await func(self, *args, **kwargs)
        try:
            new_page = await new_page_future
            await new_page.wait_for_load_state()
            self.page = new_page
        except:
            pass

        return result

    return wrapper


class Browser:
    def __init__(
        self,
        headless=True,
        cache_dir: Optional[str] = None,
        channel: Literal["chrome", "msedge", "chromium"] = "chromium",
    ):
        self.history: list = []
        self.headless = headless
        self.channel = channel
        self.page_history: list = []  # stores the history of visited pages

        # Set the cache directory
        self.cache_dir = "tmp/" if cache_dir is None else cache_dir
        os.makedirs(self.cache_dir, exist_ok=True)

    async def init(self) -> None:
        """Initialize the browser."""
        # Start playwright
        self.playwright = await async_playwright().start()
        # Launch the browser, if headless is False, the browser will display
        self.browser = await self.playwright.chromium.launch(
            headless=self.headless, channel=self.channel
        )
        # Create a new context
        self.context = await self.browser.new_context(accept_downloads=True)
        # Create a new page
        self.page = await self.context.new_page()

    async def _wait_for_load(self, timeout: int = 20) -> None:
        """Wait for a certain amount of time for the page to load."""
        timeout_ms = timeout * 1000

        await self.page.wait_for_load_state("load", timeout=timeout_ms)

    async def visit_page(self, url: str) -> None:
        """Visit a page with the given URL."""

        if not url.startswith("http://") and not url.startswith("https://"):
            url = "http://" + url

        await self.page.goto(url)
        await self._wait_for_load()

        return "Successfully visited page: " + url

    async def get_screenshot(self) -> Tuple[Image.Image, Union[str, None]]:
        r"""Get a screenshot of the current page.

        Args:
            save_image (bool): Whether to save the image to the cache
                directory.

        Returns:
            Tuple[Image.Image, str]: A tuple containing the screenshot
            image and the path to the image file if saved, otherwise
            :obj:`None`.
        """

        image_data = await self.page.screenshot(timeout=60000)
        image = Image.open(io.BytesIO(image_data))

        timestamp = datetime.datetime.now().strftime("%m%d%H%M%S")
        file_path = os.path.join(self.cache_dir, f"screenshot_{timestamp}.png")
        with open(file_path, "wb") as f:
            image.save(f, "PNG")
        f.close()

        return image, file_path

    async def get_webpage_content(self) -> str:
        await self._wait_for_load()
        text_contents = await self.page.evaluate(
            """
() => {
    // Extract clickable elements
    const clickables = Array.from(document.querySelectorAll(
        'a, button, input[type="button"], input[type="submit"], [onclick], [role="button"]'
    )).map(element => ({
        type: element.tagName.toLowerCase(),
        text: element.textContent.trim() || element.value || '',
        href: element.href || ''
    }));

    // Extract accessible forms (not hidden)
    const forms = Array.from(document.querySelectorAll('form')).filter(form => {
    const style = window.getComputedStyle(form);
    return style.display !== 'none' && style.visibility !== 'hidden';
    }).map(form => ({
    id: form.id || '',
    action: form.action || '',
    inputs: Array.from(form.querySelectorAll('input:not([type="hidden"]), select, textarea')).map(input => ({
        type: input.type || input.tagName.toLowerCase(),
        name: input.name || '',
        value: input.value || ''
    }))
    }));

    return { clickables, forms };
}
"""
        )
        return text_contents

    async def scroll_up(self) -> None:
        """Scroll up the page."""
        await self.page.keyboard.press("PageUp")

    async def scroll_down(self) -> None:
        """Scroll down the page."""
        await self.page.keyboard.press("PageDown")

    async def fill_form(self, form_name: str, value: str) -> None:
        """Fill a form element with the given value."""

        await self.page.locator(f"[name='{form_name}']").fill(value)
        return f"Filled element with form '{form_name}' with value {value}"

    @update_page_after_click
    async def click_text(self, text: str) -> None:
        """Click an element with the given text and track page history."""
        current_url = self.page.url
        await self.page.locator(f"text={text}").nth(0).click()

        # If we're on a new URL after clicking, add the previous URL to history
        if current_url != self.page.url:
            self.page_history.append(current_url)

        return f"Clicked element with text {text}"

    async def back(self):
        """Navigate back to the previous page."""

        page_url_before = self.page.url
        await self.page.go_back()

        page_url_after = self.page.url

        if page_url_after == "about:blank":
            await self.visit_page(page_url_before)

        if page_url_before == page_url_after:
            # If the page is not changed, try to use the history
            if len(self.page_history) > 0:
                await self.visit_page(self.page_history.pop())

        await asyncio.sleep(1)
        await self._wait_for_load()
