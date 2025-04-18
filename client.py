import asyncio
import json
import os
import sys
from typing import List

from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.sse import sse_client
from openai import AsyncOpenAI
import json

from utils import download_image

load_dotenv()

INVISIBLE_PARAMETERS = json.loads(os.getenv("INVISIBLE_PARAMETERS", []))

TOOL_USE_SYSTEM_PROMPT = """
1. 首先调用visite_page函数，打开网页。
2. 然后可以调用fill_form函数，填写表单；click_text函数，点击文本；scroll_up函数，向上滚动；scroll_down函数，向下滚动；back函数，返回上一个页面。

注意：每次只能调用一个工具。
"""


class MCPClient:
    def __init__(
        self, model_name: str, base_url: str, api_key: str, server_urls: List[str]
    ):
        """
        初始化 MCP 客户端，连接 OpenAI 接口。

        :param model_name: 使用的模型名称，例如 "deepseek-chat"。
        :param base_url: OpenAI 接口的基础地址，例如 "https://api.deepseek.com/v1"。
        :param api_key: OpenAI API 密钥，用于身份验证。
        :param server_urls: SSE 服务地址列表，用于连接多个服务器。
        """
        self.CURRENT_SANDBOX_ID = "client1"
        self.model_name = model_name
        self.server_urls = server_urls
        self.sessions = (
            {}
        )  # 存储每个服务器的会话及其上下文：server_id -> (session, session_context, streams_context)
        self.tool_mapping = (
            {}
        )  # 工具映射：prefixed_name -> (session, original_tool_name)

        # 初始化 OpenAI 异步客户端
        self.client = AsyncOpenAI(base_url=base_url, api_key=api_key)

    async def initialize_sessions(self):
        """
        初始化与所有 SSE 服务器的连接，并获取可用工具列表。
        """
        for i, server_url in enumerate(self.server_urls):
            server_id = f"server{i}"  # 为每个服务器生成唯一标识符
            # 创建 SSE 客户端并进入上下文
            streams_context = sse_client(url=server_url)
            streams = await streams_context.__aenter__()
            session_context = ClientSession(*streams)
            session = await session_context.__aenter__()
            await session.initialize()

            # 存储会话及其上下文
            self.sessions[server_id] = (session, session_context, streams_context)

            # 获取工具列表并建立映射
            response = await session.list_tools()
            for tool in response.tools:
                prefixed_name = f"{server_id}_{tool.name}"  # 为工具名添加服务器前缀
                self.tool_mapping[prefixed_name] = (session, tool.name)
            print(
                f"已连接到 {server_url}，工具列表：{[tool.name for tool in response.tools]}"
            )

    async def cleanup(self):
        """
        清理所有会话和连接资源，确保无资源泄漏。
        """
        for server_id, (
            session,
            session_context,
            streams_context,
        ) in self.sessions.items():
            await session_context.__aexit__(None, None, None)  # 退出会话上下文
            await streams_context.__aexit__(None, None, None)  # 退出 SSE 流上下文
        print("所有会话已清理。")

    async def process_query(self, query: str) -> str:
        """
        处理用户的自然语言查询，通过工具调用完成任务并返回结果。

        :param query: 用户输入的查询字符串。
        :return: 处理后的回复文本。
        """
        messages = [
            {"role": "system", "content": TOOL_USE_SYSTEM_PROMPT},
            {"role": "user", "content": query},
        ]

        # 收集所有可用工具
        available_tools = []
        for server_id, (session, _, _) in self.sessions.items():
            response = await session.list_tools()
            for tool in response.tools:
                prefixed_name = f"{server_id}_{tool.name}"
                # 过滤掉不可见的参数，生成新的参数列表
                filtered_properties = {
                    param: details
                    for param, details in tool.inputSchema["properties"].items()
                    if param not in INVISIBLE_PARAMETERS
                }
                filtered_required = [
                    param
                    for param in tool.inputSchema["required"]
                    if param not in INVISIBLE_PARAMETERS
                ]
                tool.inputSchema["properties"] = filtered_properties
                tool.inputSchema["required"] = filtered_required
                available_tools.append(
                    {
                        "type": "function",
                        "function": {
                            "name": prefixed_name,
                            "description": tool.description,
                            "parameters": tool.inputSchema,
                        },
                    }
                )

        # 向模型发送初始请求
        response = await self.client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            tools=available_tools,
        )

        final_text = []  # 存储最终回复内容
        message = response.choices[0].message
        final_text.append(message.content or "")  # 添加模型的初始回复

        # 处理工具调用
        while message.tool_calls:
            for tool_call in message.tool_calls:
                prefixed_name = tool_call.function.name
                if prefixed_name in self.tool_mapping:
                    session, original_tool_name = self.tool_mapping[prefixed_name]
                    tool_args = json.loads(tool_call.function.arguments)
                    for param_name in INVISIBLE_PARAMETERS:
                        tool_args[param_name] = self.__getattribute__(param_name)
                    try:
                        print(f"调用工具 {prefixed_name}，参数: {tool_args}")
                        result = await session.call_tool(original_tool_name, tool_args)
                    except Exception as e:
                        result = {
                            "content": f"调用工具 {original_tool_name} 出错：{str(e)}"
                        }
                        print(result["content"])
                    final_text.append(f"[调用工具 {prefixed_name} 参数: {tool_args}]")
                    final_text.append(f"工具结果: {result.content}")
                    messages.extend(
                        [
                            {
                                "role": "assistant",
                                "tool_calls": [
                                    {
                                        "id": tool_call.id,
                                        "type": "function",
                                        "function": {
                                            "name": prefixed_name,
                                            "arguments": json.dumps(tool_args),
                                        },
                                    }
                                ],
                            },
                            {
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "content": str(result.content),
                            },
                        ]
                    )
                    result = await session.call_tool(
                        "get_last_screenshot",
                        {"CURRENT_SANDBOX_ID": self.CURRENT_SANDBOX_ID},
                    )
                    url = result.content[0].text
                    messages.append(
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": download_image(url)
                                    },
                                },
                                {"type": "text", "text": "当前页面的截图"},
                            ],
                        }
                    )
                else:
                    print(f"工具 {prefixed_name} 未找到")
                    final_text.append(f"工具 {prefixed_name} 未找到")

            # 获取工具调用后的后续回复
            response = await self.client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                tools=available_tools,
            )
            message = response.choices[0].message
            if message.content:
                final_text.append(message.content)

        return "\n".join(final_text)

    async def chat_loop(self):
        """
        启动命令行交互式对话循环，接受用户输入并显示回复。
        """
        print("\nMCP 客户端已启动，输入你的问题，输入 'quit' 退出。")
        while True:
            try:
                query = input("\n问题: ").strip()
                if query.lower() == "quit":
                    break
                response = await self.process_query(query)
                print("\n" + response)
            except Exception as e:
                print(f"\n发生错误: {str(e)}")


async def main():
    """
    程序入口，设置配置并启动 MCP 客户端。
    """
    # 从环境变量获取配置
    model_name = os.getenv("MODEL_NAME", "deepseek-chat")
    base_url = os.getenv("BASE_URL", "https://api.deepseek.com/v1")
    api_key = os.getenv("API_KEY", "sk-")
    # 定义 SSE 服务器地址列表
    server_urls = ["http://10.12.182.155:8888/sse"]

    # 创建并运行客户端
    client = MCPClient(
        model_name=model_name,
        base_url=base_url,
        api_key=api_key,
        server_urls=server_urls,
    )
    try:
        await client.initialize_sessions()
        await client.chat_loop()
    finally:
        await client.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
