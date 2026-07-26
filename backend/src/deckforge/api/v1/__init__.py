"""API version 1."""

from fastapi import APIRouter

from deckforge.api.v1 import catalog, conversations, exports, llm, presentations

router = APIRouter()
router.include_router(conversations.router)
router.include_router(presentations.router)
router.include_router(exports.router)
router.include_router(llm.router)
router.include_router(catalog.router)

__all__ = ["router"]
