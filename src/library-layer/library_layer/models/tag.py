"""Tag, Genre, and Category domain models."""

from pydantic import BaseModel, ConfigDict


class Tag(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    name: str
    slug: str
    votes: int = 0
    category: str = "Other"


class Genre(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str


class Category(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    appid: int
    category_id: int
    category_name: str
