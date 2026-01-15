from dataclasses import dataclass


@dataclass
class GroupChatDeps:
    """Dependencies for group chat agent."""

    user_id: int
    group_id: int
