"""Tag application service — CRUD and hierarchy resolution."""

from __future__ import annotations

import time

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from things_sdk.cloud.protocol import generate_uuid
from things_sdk.db.models import Tag, TaskTag
from things_sdk.errors import EntityNotFoundError, ThingsSDKError


class AmbiguousTagError(ThingsSDKError):
    """Raised when a tag name matches multiple tags at different hierarchy levels."""

    def __init__(self, name: str, candidates: list[str]):
        self.name = name
        self.candidates = candidates
        super().__init__(f"Ambiguous tag name '{name}', matches: {', '.join(candidates)}")


class TagService:
    async def create_tag(
        self,
        session: AsyncSession,
        *,
        title: str,
        parent: str | None = None,
        shortcut: str | None = None,
    ) -> dict:
        parent_uuid = None
        if parent is not None:
            parent_tag = await self.resolve_tag(session, parent)
            parent_uuid = parent_tag["uuid"]

        tag = Tag(
            uuid=generate_uuid(),
            title=title,
            parent_uuid=parent_uuid,
            shortcut=shortcut,
            index=0,
            pending_push=True,
            is_new=True,
        )
        session.add(tag)
        await session.commit()
        return self._tag_to_dict(tag)

    async def update_tag(
        self,
        session: AsyncSession,
        uuid: str,
        *,
        title: str | None = None,
        parent: str | None = ...,  # type: ignore[assignment]
        shortcut: str | None = ...,  # type: ignore[assignment]
    ) -> dict:
        result = await session.execute(select(Tag).where(Tag.uuid == uuid))
        tag = result.scalar_one_or_none()
        if not tag:
            raise EntityNotFoundError("Tag", uuid)

        if title is not None:
            tag.title = title
        if parent is not ...:
            if parent is not None:
                parent_tag = await self.resolve_tag(session, parent)
                tag.parent_uuid = parent_tag["uuid"]
            else:
                tag.parent_uuid = None
        if shortcut is not ...:
            tag.shortcut = shortcut

        tag.pending_push = True
        await session.commit()
        return self._tag_to_dict(tag)

    async def delete_tag(self, session: AsyncSession, uuid: str) -> None:
        result = await session.execute(select(Tag).where(Tag.uuid == uuid))
        tag = result.scalar_one_or_none()
        if not tag:
            raise EntityNotFoundError("Tag", uuid)

        # Mark for push deletion (actual delete happens after push sync)
        tag.pending_delete = True
        tag.pending_push = False
        await session.commit()

    async def list_tags(self, session: AsyncSession) -> list[dict]:
        result = await session.execute(select(Tag).where(Tag.pending_delete == False).order_by(Tag.index))
        return [self._tag_to_dict(t) for t in result.scalars()]

    async def get_tag(self, session: AsyncSession, uuid: str) -> dict:
        result = await session.execute(select(Tag).where(Tag.uuid == uuid))
        tag = result.scalar_one_or_none()
        if not tag:
            raise EntityNotFoundError("Tag", uuid)
        return self._tag_to_dict(tag)

    async def resolve_tag(self, session: AsyncSession, name_or_uuid: str) -> dict:
        """Resolve a tag by UUID or hierarchical name (e.g. 'work/errands').

        Raises EntityNotFoundError if not found, AmbiguousTagError if ambiguous.
        """
        # Try UUID first (22-char hex)
        if len(name_or_uuid) == 22 and "/" not in name_or_uuid:
            result = await session.execute(select(Tag).where(Tag.uuid == name_or_uuid))
            tag = result.scalar_one_or_none()
            if tag:
                return self._tag_to_dict(tag)

        # Hierarchical name resolution
        parts = name_or_uuid.split("/")
        return await self._resolve_hierarchical(session, parts)

    async def _resolve_hierarchical(self, session: AsyncSession, parts: list[str]) -> dict:
        """Walk tag hierarchy to resolve a path like ['work', 'errands']."""
        result = await session.execute(select(Tag).where(Tag.pending_delete == False))
        all_tags = {t.uuid: t for t in result.scalars()}

        if len(parts) == 1:
            # Unqualified name — check for ambiguity
            name = parts[0]
            matches = [t for t in all_tags.values() if t.title == name]
            if not matches:
                raise EntityNotFoundError("Tag", name)
            if len(matches) == 1:
                return self._tag_to_dict(matches[0])
            # Ambiguous — build full paths for error message
            candidates = [self._build_path(t, all_tags) for t in matches]
            raise AmbiguousTagError(name, candidates)

        # Multi-part: walk from root
        current_parent: str | None = None
        tag: Tag | None = None
        for part in parts:
            matches = [
                t for t in all_tags.values()
                if t.title == part and t.parent_uuid == current_parent
            ]
            if not matches:
                raise EntityNotFoundError("Tag", "/".join(parts))
            tag = matches[0]
            current_parent = tag.uuid

        assert tag is not None
        return self._tag_to_dict(tag)

    async def get_descendants(self, session: AsyncSession, tag_uuid: str) -> list[str]:
        """Return UUIDs of all descendant tags (children, grandchildren, etc.)."""
        result = await session.execute(select(Tag).where(Tag.pending_delete == False))
        all_tags = list(result.scalars())

        children_map: dict[str | None, list[str]] = {}
        for t in all_tags:
            children_map.setdefault(t.parent_uuid, []).append(t.uuid)

        # Tag parent_uuid is supposed to form a tree, but a corrupted graph
        # (cycle introduced by a bad sync, manual DB edit, or external tool)
        # would loop forever here. Guard with a visited set.
        descendants: list[str] = []
        visited: set[str] = {tag_uuid}
        queue = list(children_map.get(tag_uuid, []))
        while queue:
            current = queue.pop()
            if current in visited:
                continue
            visited.add(current)
            descendants.append(current)
            queue.extend(children_map.get(current, []))

        return descendants

    def _build_path(self, tag: Tag, all_tags: dict[str, Tag]) -> str:
        """Build the full hierarchical path for a tag."""
        parts = [tag.title]
        current = tag
        seen: set[str] = {current.uuid}
        while current.parent_uuid and current.parent_uuid in all_tags:
            if current.parent_uuid in seen:
                break
            seen.add(current.parent_uuid)
            current = all_tags[current.parent_uuid]
            parts.append(current.title)
        parts.reverse()
        return "/".join(parts)

    def _tag_to_dict(self, t: Tag) -> dict:
        return {
            "uuid": t.uuid,
            "title": t.title,
            "shortcut": t.shortcut,
            "parent_uuid": t.parent_uuid,
            "index": t.index,
        }
