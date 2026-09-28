from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")

MAX_PAGE_SIZE = 100


class PageMeta(BaseModel):
    total: int
    limit: int
    offset: int


class Page(BaseModel, Generic[T]):  # noqa: UP046 - pydantic generic, explicit form
    """List envelope (ADR-0004): ``{"data": [...], "meta": {...}}``."""

    data: list[T]
    meta: PageMeta


class PageParams(BaseModel):
    limit: int = Field(default=25, ge=1, le=MAX_PAGE_SIZE)
    offset: int = Field(default=0, ge=0, le=100_000)
