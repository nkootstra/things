"""API-facing tag service that adapts SDK errors to HTTP exceptions."""

from fastapi import HTTPException

from things_api.services.contracts import TagServiceProtocol
from things_sdk import AmbiguousTagError, EntityNotFoundError
from things_sdk import TagService as SDKTagService


class TagService(TagServiceProtocol):
    def __init__(self) -> None:
        self._sdk = SDKTagService()

    async def create_tag(self, session, *, title, parent=None, shortcut=None):
        try:
            return await self._sdk.create_tag(
                session, title=title, parent=parent, shortcut=shortcut
            )
        except EntityNotFoundError:
            raise HTTPException(status_code=404, detail="Parent tag not found")
        except AmbiguousTagError as e:
            raise HTTPException(status_code=422, detail=str(e))

    async def update_tag(self, session, uuid, **kwargs):
        try:
            return await self._sdk.update_tag(session, uuid, **kwargs)
        except EntityNotFoundError:
            raise HTTPException(status_code=404, detail="Tag not found")

    async def delete_tag(self, session, uuid):
        try:
            await self._sdk.delete_tag(session, uuid)
        except EntityNotFoundError:
            raise HTTPException(status_code=404, detail="Tag not found")

    async def list_tags(self, session):
        return await self._sdk.list_tags(session)

    async def get_tag(self, session, uuid):
        try:
            return await self._sdk.get_tag(session, uuid)
        except EntityNotFoundError:
            raise HTTPException(status_code=404, detail="Tag not found")


def get_tag_service() -> TagServiceProtocol:
    return TagService()
