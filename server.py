import threading
from typing import Any, Callable
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from browser import Browser
from utils import upload_files


load_dotenv()

# Initialize FastMCP server
port = 8888
host = "0.0.0.0"

mcp = FastMCP("browser", port=port, host=host)


# 存储所有的 Browser 实例
browser_map = {}
browser_map_lock = threading.Lock()

TOOL_OBSERVATION_TEMPLATE = """
### 执行反馈
<<FEEDBACK>>

### 当前页面的按钮和表单
<<INTERACTION>>

### 当前页面的屏幕截图
<<URL>>
"""
LAST_SCREEN_SHOT = {}


async def get_or_create_browser(CURRENT_SANDBOX_ID: str) -> Browser:
    """获取或创建一个浏览器实例。"""
    with browser_map_lock:
        if CURRENT_SANDBOX_ID not in browser_map:
            browser = Browser(headless=True, cache_dir=None, channel="chromium")
            try:
                await browser.init()
                browser_map[CURRENT_SANDBOX_ID] = browser
            except Exception as e:
                raise RuntimeError(f"Failed to initialize browser: {str(e)}") from e
        return browser_map[CURRENT_SANDBOX_ID]


async def get_screenshot(CURRENT_SANDBOX_ID: str) -> Any:
    """获取当前页面的截图。"""
    global LAST_SCREEN_SHOT
    _, file_path = await with_browser(CURRENT_SANDBOX_ID, lambda browser: browser.get_screenshot())
    upload_result = upload_files([file_path], upload_path="screenshot", overwrite=True)
    url = upload_result["data"]["url"]
    LAST_SCREEN_SHOT[CURRENT_SANDBOX_ID] = url
    return url


async def get_webpage_content(CURRENT_SANDBOX_ID: str) -> Any:
    """获取当前页面的 HTML 内容。"""
    return await with_browser(CURRENT_SANDBOX_ID, lambda browser: browser.get_webpage_content())


async def with_browser(CURRENT_SANDBOX_ID: str, action: callable, *args, **kwargs) -> Any:
    """Helper function to execute a browser action with a given browser instance."""
    browser = await get_or_create_browser(CURRENT_SANDBOX_ID)
    return await action(browser, *args, **kwargs)


async def call_browser_with_observation(
    CURRENT_SANDBOX_ID: str, action: Callable, *args, **kwargs
) -> Any:
    """调用浏览器并观察执行结果"""
    result = await with_browser(CURRENT_SANDBOX_ID, action, *args, **kwargs)
    content = await get_webpage_content(CURRENT_SANDBOX_ID)
    screenshot_url = await get_screenshot(CURRENT_SANDBOX_ID)
    observation = (
        TOOL_OBSERVATION_TEMPLATE.replace("<<FEEDBACK>>", result)
        .replace("<<INTERACTION>>", str(content))
        .replace("<<URL>>", screenshot_url)
    )
    return observation


@mcp.tool()
def get_last_screenshot(CURRENT_SANDBOX_ID):
    """获得最后一次的截图"""
    global LAST_SCREEN_SHOT
    url = LAST_SCREEN_SHOT[CURRENT_SANDBOX_ID]
    LAST_SCREEN_SHOT[CURRENT_SANDBOX_ID] = None
    return url


@mcp.tool()
async def visit_page(CURRENT_SANDBOX_ID: str, url: str) -> Any:
    """访问指定的页面。"""
    return await call_browser_with_observation(
        CURRENT_SANDBOX_ID, lambda browser: browser.visit_page(url)
    )


@mcp.tool()
async def scroll_down(CURRENT_SANDBOX_ID: str) -> Any:
    """向下滚动页面。"""
    return await call_browser_with_observation(
        CURRENT_SANDBOX_ID, lambda browser: browser.scroll_down()
    )


@mcp.tool()
async def scroll_up(CURRENT_SANDBOX_ID: str) -> Any:
    """向上滚动页面。"""
    return await call_browser_with_observation(CURRENT_SANDBOX_ID, lambda browser: browser.scroll_up())


@mcp.tool()
async def fill_form(CURRENT_SANDBOX_ID: str, form_name: str, value: str) -> Any:
    """填写表单。"""
    return await call_browser_with_observation(
        CURRENT_SANDBOX_ID, lambda browser: browser.fill_form(form_name, value)
    )


@mcp.tool()
async def click_text(CURRENT_SANDBOX_ID: str, text: str) -> Any:
    """点击指定文本的元素。"""
    return await call_browser_with_observation(
        CURRENT_SANDBOX_ID, lambda browser: browser.click_text(text)
    )


@mcp.tool()
async def back(CURRENT_SANDBOX_ID: str) -> Any:
    """后退到上一页。"""
    return await call_browser_with_observation(CURRENT_SANDBOX_ID, lambda browser: browser.back())


if __name__ == "__main__":
    print("start server")
    mcp.run(transport="sse")
