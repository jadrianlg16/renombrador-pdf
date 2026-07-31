from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class Selection(BaseModel):
    page: int = Field(ge=1)
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)

    @field_validator("width")
    @classmethod
    def validate_width(cls, value: float) -> float:
        if value < 0.001:
            raise ValueError("La selección es demasiado angosta")
        return value

    @field_validator("height")
    @classmethod
    def validate_height(cls, value: float) -> float:
        if value < 0.001:
            raise ValueError("La selección es demasiado baja")
        return value


class OCRRequest(BaseModel):
    selections: list[Selection] = Field(min_length=1, max_length=20)


class ApproveRequest(BaseModel):
    name: str = Field(min_length=1, max_length=220)
    ocr_text: str | None = None
    selections: list[Selection] = Field(default_factory=list, max_length=20)
