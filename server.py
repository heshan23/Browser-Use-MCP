import threading
from typing import Any, Callable
from mcp.server.fastmcp import FastMCP
from browser import Browser
from utils import upload_files

# Initialize FastMCP server
port = 8888
host = "0.0.0.0"

mcp = FastMCP("browser", port=port, host=host)


# 存储所有的 Browser 实例
browser_map = {}
browser_map_lock = threading.Lock()


async def get_or_create_browser(id: str) -> Browser:
    """获取或创建一个浏览器实例。"""
    with browser_map_lock:
        if id not in browser_map:
            browser = Browser(headless=True, cache_dir=None, channel="chromium")
            try:
                await browser.init()
                browser_map[id] = browser
            except Exception as e:
                raise RuntimeError(f"Failed to initialize browser: {str(e)}") from e
        return browser_map[id]


async def with_browser(id: str, action: callable, *args, **kwargs) -> Any:
    """Helper function to execute a browser action with a given browser instance.
    Args:
        id (str): 浏览器实例的唯一 ID。
        action (callable): The browser action to perform.
        *args: Positional arguments to pass to the action.
        **kwargs: Keyword arguments to pass to the action.
    """
    browser = await get_or_create_browser(id)
    return await action(browser, *args, **kwargs)


@mcp.tool()
async def visit_page(id: str, url: str) -> Any:
    """访问指定的页面。
    Args:
        id (str): 浏览器实例的唯一 ID。
        url (str): 要访问的 URL。
    """
    return await with_browser(id, lambda browser: browser.visit_page(url))


@mcp.tool()
async def get_screenshot(id: str) -> Any:
    """获取当前页面的截图。
    Args:
        id (str): 浏览器实例的唯一 ID。
        save_image (bool): 是否保存截图到文件。
    """
    _, file_path = await with_browser(id, lambda browser: browser.get_screenshot())
    upload_result = upload_files([file_path], upload_path="screenshot", overwrite=True)
    url = upload_result['data']['url']
    return "Screenshot saved at: " + url  

@mcp.tool()
async def get_webpage_content(id: str) -> Any:
    """获取当前页面的 HTML 内容。
    Args:
        id (str): 浏览器实例的唯一 ID。
    """
    return await with_browser(id, lambda browser: browser.get_webpage_content())

@mcp.tool()
async def scroll_down(id: str) -> Any:
    """向下滚动页面。
    Args:
        id (str): 浏览器实例的唯一 ID。
    """
    return await with_browser(id, lambda browser: browser.scroll_down())

@mcp.tool()
async def scroll_up(id: str) -> Any:
    """向上滚动页面。
    Args:
        id (str): 浏览器实例的唯一 ID。
    """
    return await with_browser(id, lambda browser: browser.scroll_up())

@mcp.tool()
async def fill_form(id: str, form_name: str, value: str) -> Any:
    """填写表单。
    Args:
        id (str): 浏览器实例的唯一 ID。
        form_name (str): 输入框的选择器。
        value (str): 要填写的内容。
    """
    return await with_browser(id, lambda browser: browser.fill_form(form_name, value))

@mcp.tool()
async def click_text(id: str, text: str) -> Any:
    """点击指定文本的元素。
    Args:
        id (str): 浏览器实例的唯一 ID。
        text (str): 要点击的文本内容。
    """
    return await with_browser(id, lambda browser: browser.click_text(text))

@mcp.tool()
async def back(id: str) -> Any:
    """后退到上一页。
    Args:
        id (str): 浏览器实例的唯一 ID。
    """
    return await with_browser(id, lambda browser: browser.back())

if __name__ == "__main__":
    print("start server")
    mcp.run(transport="sse")
