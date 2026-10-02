"""Pydantic request bodies; they bound everything the browser can send."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class Selection(BaseModel):
    """A box drawn on a page, in fractions of the page size (0 to 1), so zoom doesn't matter."""

    page: int = Field(ge=1)
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)

    @field_validator("width")
    @classmethod
    def validate_width(cls, value: float) -> float:
        """Reject boxes too narrow to hold text."""
        if value < 0.001:
            raise ValueError("La selección es demasiado angosta")
        return value

    @field_validator("height")
    @classmethod
    def validate_height(cls, value: float) -> float:
        """Reject boxes too short to hold text."""
        if value < 0.001:
            raise ValueError("La selección es demasiado baja")
        return value


class OCRRequest(BaseModel):
    """The boxes to read, in the order their texts are joined."""

    selections: list[Selection] = Field(min_length=1, max_length=20)


class ApproveRequest(BaseModel):
    """The name a person approved, plus the OCR text and boxes it came from, for the log."""

    name: str = Field(min_length=1, max_length=220)
    ocr_text: str | None = None
    selections: list[Selection] = Field(default_factory=list, max_length=20)


class ExportRecord(BaseModel):
    """The ZIP the UI is about to download: ``folder`` None means every batch, "" the root."""

    scope: Literal["approved", "all"] = "approved"
    folder: str | None = Field(default=None, max_length=255)
