from functools import lru_cache
from typing import Any, Dict, List

from ncatbot.core import BotClient, PrivateMessage

from app import agents
from app.collector import MessageBatcher

bot = BotClient()

# Store a batcher for each user
private_batchers: Dict[int, MessageBatcher[PrivateMessage, Any]] = {}


@lru_cache(maxsize=128)
def get_private_batcher(user_id: int | str) -> MessageBatcher[PrivateMessage, None]:
    """Get or create a batcher for a specific user"""
    if user_id not in private_batchers:

        async def handle_batch(messages: List[PrivateMessage]) -> None:
            result = await agents.chat.run(
                user_prompt="\n".join([msg.raw_message for msg in messages])
            )
            await bot.api.post_private_msg(
                user_id=user_id,
                text=result.output,
            )

        private_batchers[int(user_id)] = MessageBatcher(
            handler=handle_batch,
            batch_delay=1,
        )

    return private_batchers[int(user_id)]


@bot.private_event()  # pyright: ignore[reportArgumentType]
async def on_private_message(msg: PrivateMessage):
    # Get batcher for this user and push message
    batcher = get_private_batcher(msg.user_id)
    await batcher.push(msg)


if __name__ == "__main__":
    bot.run()
