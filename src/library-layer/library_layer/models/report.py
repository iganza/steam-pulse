"""Report domain model."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class Report(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    appid: int
    report_json: dict
    reviews_analyzed: int = 0
    analysis_version: str | None = None
    is_public: bool = False
    seo_title: str | None = None
    seo_description: str | None = None
    last_analyzed: datetime | None = None
    created_at: datetime | None = None
