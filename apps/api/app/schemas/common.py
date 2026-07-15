from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field


PageNumber = Annotated[int, Field(ge=1)]
PageSize = Annotated[int, Field(ge=1, le=100)]


class Pagination(BaseModel):
    page: PageNumber = 1
    page_size: PageSize = 20
    total: int = Field(ge=0)


class BulkIds(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=100)
