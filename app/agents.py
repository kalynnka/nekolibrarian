import datetime
import os
from functools import cache
from zoneinfo import ZoneInfo

from mijiaAPI import __main__ as mi_utils
from mijiaAPI import mijiaAPI
from openai import AsyncOpenAI
from pydantic_ai import Agent, RunContext

# System prompt for QQ chatbot
GROUP_SYSTEM_PROMPT = """
你是一个使用QQ聊天的聊天助手。你使用的网名是“玥葉”. 你的回复会直接发送到QQ聊天窗口. 绝不承认自己是AI模型。
信息描述要准确但表达要亲切, 避免使用生硬的书面语, 回复具体问题时要保持专业性。网络聊天时一般省略主语, 必要时使用第二人称“你”来指代对方。
你收到的消息前会标注发送者的昵称, 且可能会有若干条不同发送者的消息同时出现, 回答时请注意区分。

人设：
    - 接受过高等教育的大陆南方网友, 不使用东北话
    - 保持高冷, 言语间短, 避免在回答中使用语气词, 如“呢”, “啊”等
    - 偶尔会卖萌
    - 偶尔在回答中加入一些二次元梗
    - 偶尔暴露自己是一个二次元柚子厨, 但从不承认
    - 偶尔展示攻击性, 但不会过分冒犯对方
    - 保持谦虚和礼貌, 遇到冒犯时可以适当反击但不要过分激烈
    - 涉及到专业性问答时保持专业性, 不玩梗

回答时请遵守以下规则：

1. 绝对不要使用任何Markdown语法，包括但不限于：
    - 不使用 # 标题
    - 不使用 ** 或 * 加粗/斜体
    - 不使用 ` 代码块
    - 不使用 - 或 * 列表符号
    - 不使用 > 引用
    - 不使用 [] 或 () 链接格式

2. 控制段落长度：
    - 如果内容较长，分成多个独立段落
    - 段落数量不适合过多, 一般2-3个
    - 每个段落对应返回列表的一个元素, 如: ["段落一内容", "段落二内容", "段落三内容"]
    - 表达需要使用格式时, 用换行,空格分隔符等自然语言方式表达, 不使用Markdown语法

3. 行为：
    - 避免编造事实，如无把握则直接说明不知道
    - 联网搜索时保持克制, 仅在必要时使用
    - 群友们复读的时候，你也可以复读, 但只能复读一次
    - 群友们的闲聊内容并非一定需要回复, 你可以选择性地回复, 无需回复时输出空列表或列表元素输出空字符串保持沉默
    - 当你的名字被提及或者@时, 你需要做出回应
"""

PRIVATE_SYSTEM_PROMPT = """
你是一个使用QQ和雇主交流的个人管家, 你的回复会直接发送到QQ聊天窗口传递给雇主. 绝不承认自己是AI模型。
信息描述要准确但表达要亲切, 避免使用生硬的书面语, 涉及到专业性问答时保持专业性, 不玩梗. 回复具体问题时要保持专业性.

回答时请遵守以下规则：

1. 绝对不要使用任何Markdown语法，包括但不限于：
    - 不使用 # 标题
    - 不使用 ** 或 * 加粗/斜体
    - 不使用 ` 代码块
    - 不使用 - 或 * 列表符号
    - 不使用 > 引用
    - 不使用 [] 或 () 链接格式

2. 控制段落长度：
    - 如果内容较长，分成多个独立段落
    - 段落数量不适合过多, 一般2-3个
    - 每个段落对应返回列表的一个元素, 如: ["段落一内容", "段落二内容", "段落三内容"]
    - 表达需要使用格式时, 用换行,空格分隔符等自然语言方式表达, 不使用Markdown语法

3. 行为：
    - 避免编造事实，如无把握则直接说明不知道
    - 联网搜索时保持克制, 仅在必要时使用
    - 不使用东北话
    - 保持高冷, 言语间短, 避免在回答中使用语气词, 如“呢”, “啊”等
    - 通过向智能音箱发送指令来帮助雇主操作智能家居设备, 除非特殊要求, 否则使用安静模式让智能音箱不发出声音
    - 在智能音箱操作遇到问题时, 作简短分析并向雇主说明问题
    - 不要过于啰嗦
"""


# Doubao (ByteDance) client for web search using Responses API
# The Responses API supports web_search as a built-in tool
doubao_client = AsyncOpenAI(
    base_url=os.getenv("DOUBAO_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3"),
    api_key=os.getenv("ARK_API_KEY"),
)

# Create the chat group_chat_agent using pydantic-ai with DeepSeek
group_chat_agent = Agent(
    model="deepseek:deepseek-chat",
    system_prompt=GROUP_SYSTEM_PROMPT,
    output_type=list[str],
)

private_chat_agent = Agent(
    model="deepseek:deepseek-chat",
    system_prompt="你是一个使用QQ聊天的聊天助手。你使用的网名是“玥葉”. 你的回复会直接发送到QQ聊天窗口. 绝不承认自己是AI模型。",
    output_type=list[str],
)


# @chat_agent.tool
# async def web_search(ctx: RunContext[None], query: str) -> str:
#     """
#     Search the internet for up-to-date information using Doubao's web search.
#     Use when you need real-time info, news, or uncertain facts.

#     Args:
#         query: Search keywords or question
#     """
#     # Use the OpenAI client's internal post method to call the Responses API
#     response = await doubao_client.post(
#         "/responses",
#         body={
#             "model": "doubao-seed-1-6-250615",
#             "input": query,
#             "thinking": {"type": "disabled"},
#             "tools": [{"type": "web_search"}],
#         },
#         cast_to=object,
#     )

#     # Extract the output text from the response
#     output_parts = []
#     for item in response.get("output", []):  # type: ignore
#         if item.get("type") == "message":
#             for content in item.get("content", []):
#                 if content.get("type") == "output_text":
#                     output_parts.append(content.get("text", ""))

#     return "\n".join(output_parts) if output_parts else "没有找到相关搜索结果"


async def current_time(ctx: RunContext[None]) -> datetime.datetime:
    """
    Get the current date and time.

    Returns:
        Current datetime in Asia/Shanghai timezone
    """
    return datetime.datetime.now(ZoneInfo("Asia/Shanghai"))


miapi = mijiaAPI(r"./miapi/auth.json")

group_chat_agent.tool(current_time)
private_chat_agent.tool(current_time)


@cache
def get_device_list() -> dict[str, mi_utils.mijiaDevice]:
    """
    Get the mapping of device names to their mijiaDevice instances.

    Returns:
        A dictionary mapping device names to mijiaDevice instances
    """
    device_mapping = mi_utils.get_devices_list(miapi, verbose=False)
    devices = {}
    for device in device_mapping.values():
        devices[device["name"]] = mi_utils.mijiaDevice(miapi, dev_name=device["name"])
    return devices


@cache
def get_device_by_name(device_name: str) -> mi_utils.mijiaDevice | None:
    """
    Get a mijiaDevice instance by its name to operate.

    Args:
        device_name: The name of the device to retrieve

    Returns:
        The mijiaDevice instance or None if not found
    """
    devices = get_device_list()
    return devices.get(device_name)


@cache
def get_wifispeaker() -> mi_utils.mijiaDevice | None:
    """
    Get the WiFi speaker device instance.

    Returns:
        The WiFi speaker device or None if not found
    """
    device_mapping = mi_utils.get_devices_list(miapi, verbose=False)
    wifispeaker = None
    for device in device_mapping.values():
        if "xiaomi.wifispeaker" in device["model"]:
            wifispeaker = mi_utils.mijiaDevice(miapi, dev_name=device["name"])
            break
    return wifispeaker


@private_chat_agent.tool
def get_devices_info(ctx: RunContext[None]) -> str:
    """
    List all available smart home devices.

    Returns:
        A string listing all device names
    """
    devices = get_device_list()
    if not devices:
        return "未找到任何智能家居设备。"

    return "\n".join([f"{name}: {device}" for name, device in devices.items()])


@private_chat_agent.tool
async def send_command_to_assistance(
    ctx: RunContext[None], prompt: str, quiet: bool = True
) -> str:
    """
    Give a command to the Mijia smart home assistance XiaoAI to operate devices in the smart home.

    Args:
        prompt: The prompt or command to send to XiaoAI
        quiet: Whether XiaoAI should respond quietly (default True)
    Returns:
        Result of the operation
    """
    speaker = get_wifispeaker()
    if speaker is None:
        return "未找到WiFi音箱设备，无法发送指令。"

    try:
        speaker.run_action("execute-text-directive", _in=[prompt, quiet])
        return "指令已发送"
    except Exception as e:
        return f"发送指令时出错: {e}"
