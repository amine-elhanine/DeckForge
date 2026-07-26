"""Repositories for users, conversations and messages."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, select

from deckforge.database.entities import Conversation, Message, User
from deckforge.database.repositories.base import Repository

LOCAL_USER_ID = "usr_local"


class UserRepository(Repository[User]):
    model = User

    async def get_or_create_local(self) -> User:
        """Return the singleton local user, creating it on first run."""
        user = await self.get(LOCAL_USER_ID)
        if user is None:
            user = User(id=LOCAL_USER_ID, display_name="Local user", preferences={})
            await self.add(user)
        return user


class ConversationRepository(Repository[Conversation]):
    model = Conversation

    async def list_for_user(
        self, user_id: str, *, include_archived: bool = False, limit: int = 200
    ) -> Sequence[Conversation]:
        stmt = (
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.updated_at.desc())
            .limit(limit)
        )
        if not include_archived:
            stmt = stmt.where(Conversation.archived.is_(False))
        return (await self.session.execute(stmt)).scalars().all()

    async def search(self, user_id: str, query: str, limit: int = 50) -> Sequence[Conversation]:
        pattern = f"%{query.lower()}%"
        stmt = (
            select(Conversation)
            .where(
                Conversation.user_id == user_id,
                func.lower(Conversation.title).like(pattern),
            )
            .order_by(Conversation.updated_at.desc())
            .limit(limit)
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def touch(self, conversation: Conversation) -> None:
        """Bump ``updated_at`` so the sidebar ordering stays fresh."""
        from deckforge.database.base import utcnow

        conversation.updated_at = utcnow()
        await self.session.flush()


class MessageRepository(Repository[Message]):
    model = Message

    async def history(self, conversation_id: str, limit: int = 200) -> Sequence[Message]:
        stmt = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc(), Message.id.asc())
            .limit(limit)
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def recent(self, conversation_id: str, limit: int = 20) -> list[Message]:
        stmt = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(limit)
        )
        rows = list((await self.session.execute(stmt)).scalars().all())
        rows.reverse()
        return rows
