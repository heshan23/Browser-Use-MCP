import asyncio
import datetime
from functools import wraps
import io
import os
from typing import Any, Callable, Dict, List, Literal, Optional, Tuple, Union

from PIL import Image
from playwright.async_api import async_playwright


def async_exception_handler_with_retry(
    exceptions: Tuple[type, ...] = (TimeoutError, Exception),
    retries: int = 3,
    delay: float = 1.0,
) -> Callable:
    """Decorator to handle exceptions in async functions with retries.

    Args:
        exceptions: Tuple of exception types to catch.
        retries: Number of retry attempts.
        delay: Delay between retries in seconds.

    Returns:
        Callable: Decorated function with retry logic.
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            for attempt in range(retries):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    if attempt == retries - 1:
                        return f"Failed after {retries} attempts in {func.__name__}: {type(e).__name__} - {str(e)}"
                    await asyncio.sleep(delay)
            return None  # Ensure a return value in case of exhaustion
        return wrapper
    return decorator


def update_page_after_click(func: Callable) -> Callable:
    """Decorator to update the page after a click event, handling new pages.

    Captures new page events and updates the instance's page reference.
    """
    @async_exception_handler_with_retry()
    async def wrapper(self: 'Browser', *args: Any, **kwargs: Any) -> Any:
        new_page_future = asyncio.ensure_future(
            self.context.wait_for_event("page", timeout=3000)
        )
        try:
            result = await func(self, *args, **kwargs)
        except Exception as e:
            new_page_future.cancel()
            raise
        new_page = await new_page_future
        await new_page.wait_for_load_state()
        self.page = new_page
        return result
    return wrapper


class Browser:
    """A class to interact with web pages using Playwright for automation.

    Attributes:
        headless: Whether to run the browser in headless mode.
        channel: Browser channel to use (e.g., 'chromium', 'chrome', 'msedge').
        cache_dir: Directory to store screenshots and cached files.
        history: List of visited URLs.
        page_history: List of previous page URLs for navigation.
    """
    def __init__(
        self,
        headless: bool = True,
        cache_dir: Optional[str] = None,
        channel: Literal["chrome", "msedge", "chromium"] = "chromium",
    ) -> None:
        self.headless = headless
        self.channel = channel
        self.cache_dir = cache_dir or "tmp/"
        os.makedirs(self.cache_dir, exist_ok=True)
        self.page_history: List[str] = []
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

    async def init(self) -> None:
        """Initialize the Playwright browser instance."""
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=self.headless, channel=self.channel
        )
        self.context = await self.browser.new_context(accept_downloads=True)
        self.page = await self.context.new_page()

    async def _wait_for_load(self, timeout: int = 20) -> None:
        """Wait for the page to load.

        Args:
            timeout: Maximum time to wait in seconds.
        """
        await self.page.wait_for_load_state("load", timeout=timeout * 1000)

    @async_exception_handler_with_retry()
    async def visit_page(self, url: str) -> str:
        """Visit a web page by URL.

        Args:
            url: The URL to visit. Adds 'http://' if no protocol is specified.

        Returns:
            str: Success message with the visited URL.
        """
        if not url.startswith(("http://", "https://")):
            url = f"http://{url}"
        await self.page.goto(url)
        await self._wait_for_load()
        return f"Successfully visited page: {url}"

    @async_exception_handler_with_retry()
    async def get_screenshot(self) -> Tuple[Image.Image, str]:
        """Capture a screenshot of the current page.

        Returns:
            Tuple[Image.Image, str]: The screenshot image and file path.
        """
        image_data = await self.page.screenshot(timeout=60000)
        image = Image.open(io.BytesIO(image_data))
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        file_path = os.path.join(self.cache_dir, f"screenshot_{timestamp}.png")
        image.save(file_path, "PNG")
        return image, file_path

    async def get_webpage_content(self) -> Dict[str, Any]:
        """Extract clickable elements and forms from the current page.

        Returns:
            Dict[str, Any]: Dictionary containing clickables and forms.
        """
        await self._wait_for_load()
        return await self.page.evaluate(
            """() => {
                const clickables = Array.from(document.querySelectorAll(
                    'a, button, input[type="button"], input[type="submit"], [onclick], [role="button"]'
                )).map(element => ({
                    type: element.tagName.toLowerCase(),
                    text: element.textContent.trim() || element.value || '',
                    href: element.href || ''
                }));
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
            }"""
        )

    async def scroll_up(self) -> None:
        """Scroll up the page."""
        await self.page.keyboard.press("PageUp")

    async def scroll_down(self) -> None:
        """Scroll down the page."""
        await self.page.keyboard.press("PageDown")

    @async_exception_handler_with_retry()
    async def fill_form(self, form_name: str, value: str) -> str:
        """Fill a form element with the specified value.

        Args:
            form_name: Name attribute of the form element.
            value: Value to fill in the form.

        Returns:
            str: Success message.
        """
        await self.page.locator(f"[name='{form_name}']").fill(value)
        return f"Filled form element '{form_name}' with value '{value}'"

    @update_page_after_click
    async def click_text(self, text: str) -> str:
        """Click an element containing the specified text.

        Args:
            text: Text content of the element to click.

        Returns:
            str: Success message.

        Raises:
            ValueError: If no element with the specified text is found.
        """
        current_url = self.page.url
        elements = await self.page.locator(f"text={text}").all()
        if not elements:
            raise ValueError(f"No element found with text '{text}'")
        await elements[0].click()
        if current_url != self.page.url:
            self.page_history.append(current_url)
        return f"Clicked element with text '{text}'"

    @async_exception_handler_with_retry()
    async def back(self) -> None:
        """Navigate to the previous page.

        Falls back to page history if navigation doesn't change the URL.
        """
        page_url_before = self.page.url
        await self.page.go_back()
        await self._wait_for_load()
        if self.page.url == "about:blank" or self.page.url == page_url_before:
            if self.page_history:
                await self.visit_page(self.page_history.pop())