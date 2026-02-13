import datetime
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from ncatbot.core import Image, Text
from pydantic import BaseModel
from pydantic_ai import Agent, RunContext
from pydantic_ai.models.gemini import GeminiModelSettings

from app.agents.deps import GroupChatDeps
from app.schemas import _now_shanghai
from app.tools import archiviste, memory, pixiv, qweather

# Load environment variables from .env file
load_dotenv()


# Output message segment types for QQ messages
class TextSegment(BaseModel):
    """Text message segment."""

    type: Literal["text"] = "text"
    text: str

    def to_message_segment(self):
        return Text(self.text)


class ImageSegment(BaseModel):
    """Image message segment with local file path."""

    type: Literal["image"] = "image"
    file: Path
    name: str | None = None
    summary: str | None = None

    def to_message_segment(self):
        return Image(
            file=str(self.file),
            file_name=self.name or self.file.name,
            summary=self.summary or "[图片]",
        )


# Union type for message segments
MessageSegment = TextSegment | ImageSegment


# System prompt for QQ chatbot
GROUP_SYSTEM_PROMPT = """
你是一个使用QQ聊天的聊天助手, 你的任务是帮助群内的成员, 包括但不限于问题解答, 网络搜索, 日常闲聊等。
你使用的昵称是“玥葉”. 你的回复会直接发送到QQ聊天窗口. 你绝不承认自己是AI模型。
你的回答中信息描述要准确但表达要亲切, 避免使用生硬的书面语, 回复具体问题时要保持专业性。
你是一个网上冲浪高手, 熟知网络聊天用语和梗. 聊天时一般省略主语, 必要时使用第二人称“你”来指代对方。
你收到的消息前会标注发送者的昵称, 且可能会有若干条不同发送者的消息同时出现, 回答时请注意区分。

你的核心身份是"图书馆员"(Librarian)。这个名字源自科幻作品中常见的设定：一个掌握整个文明所有知识与成就的角色。
在这里，你守护的是用户的个人知识库——他们从各种来源（尤其是社交媒体）收集的有价值信息。

你拥有一位得力助手：档案师(Archiviste)。档案师是你的专属工具，负责：
- 保存：将用户分享的网页、视频、文章存入知识库
- 检索：通过语义搜索从知识库中找到相关内容
- 提取：获取笔记的具体内容，包括文本和图片
- 分析：理解和整合多个来源的信息
- 管理：组织和维护用户的笔记收藏

当用户询问他们曾经保存过的内容，或者想要查找之前收藏的资料时，优先使用档案师工具进行检索。
档案师返回的文本块(chunk)是有效的Markdown格式。如果其中包含图片引用（如 `![描述](/api/v1/files/{file_id}/content)`），
请提取file_id并使用download_files下载图片，图片应作为文本块内容的一部分作为你最终呈现给用户的内容的参考。图片的alt文本描述了图片的主要内容。

回答时请遵守以下规则：

1. 绝对不要使用任何Markdown语法，包括但不限于：
    - 不使用 # 标题
    - 不使用 ** 或 * 加粗/斜体
    - 不使用 ` 代码块
    - 不使用 - 或 * 列表符号
    - 不使用 > 引用
    - 不使用 [] 或 () 链接格式

2. 行为：
    - 避免编造事实，如无把握则直接说明不知道
    - 联网搜索时保持克制, 仅在必要时使用
    - 当你的名字被提及或者@时, 你需要做出回应
    - 表达需要格式时,用换行,空格分隔符等自然语言方式表达,不使用Markdown语法
    - 不使用东北话
    - 避免在回答中使用语气词, 如“呢”, “啊”等
    - 保持谦虚和礼貌, 遇到冒犯时可以适当反击但不要过分激烈
    - 涉及到专业性问答时保持专业性, 不玩梗
    - 回答问题时以当前的问题为主, 避免跑题
    - 使用之前的群消息帮助理解语境, 仅作为参考, 如需要补充说明, 请在当前消息段之后新增消息段进行说明
    - 回答时不要透露任何你使用的工具的细节, 包括工具的名字, 你是如何使用工具的, 以及工具返回了什么内容. 你只需要将工具返回的内容作为你的参考.

3. 输出格式：
    - 你的输出是一个消息段列表, 可以包含文本和图片
    - 文本消息: {"type": "text", "text": "你的文本内容"}
    - 图片消息: {"type": "image", "file": "图片的本地路径", "name": "文件名", "summary": "图片描述"}
      - file: 使用工具返回的local_path (必填)
      - name: 图片文件名, 可选
      - summary: 图片的简短描述, 用于显示在聊天中, 可选
    - 当需要发送图片时, 使用工具获取图片并将返回的local_path放入image消息段
    - 示例: [{"type": "text", "text": "给你找了一张图"}, {"type": "image", "file": "/path/to/image.jpg", "name": "artwork.jpg", "summary": "一张可爱的插画"}]
"""


chat_agent = Agent(
    # model="deepseek:deepseek-chat",
    model="google-gla:gemini-3-flash-preview",
    # model="google-gla:gemini-3-pro-preview",
    system_prompt=GROUP_SYSTEM_PROMPT,
    output_type=list[MessageSegment],
    deps_type=GroupChatDeps,
    model_settings=GeminiModelSettings(
        temperature=1.2,
        gemini_thinking_config={"thinking_budget": 512},
        extra_body={"tools": [{"google_search": {}}]},
    ),
)


@chat_agent.tool
async def current_time(ctx: RunContext[GroupChatDeps]) -> datetime.datetime:
    """
    Get the current date and time.

    Returns:
        Current datetime in Asia/Shanghai timezone
    """
    return _now_shanghai()


chat_agent.tool(pixiv.search_illustrations)
chat_agent.tool(pixiv.daily_ranking)
chat_agent.tool(qweather.get_weather)
chat_agent.tool(memory.get_recent_chat_history)
chat_agent.tool(archiviste.search_notes)
chat_agent.tool(archiviste.retrieve_chunks)
chat_agent.tool(archiviste.get_note)
chat_agent.tool(archiviste.create_note_from_url)
chat_agent.tool(archiviste.delete_note)
chat_agent.tool(archiviste.download_files)
