"""Internal Pydantic models for Tencent QuestionSplitOCR responses."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class TencentModel(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class Point(TencentModel):
    x: int = Field(alias="X")
    y: int = Field(alias="Y")


class Polygon(TencentModel):
    left_top: Point | None = Field(default=None, alias="LeftTop")
    right_top: Point | None = Field(default=None, alias="RightTop")
    right_bottom: Point | None = Field(default=None, alias="RightBottom")
    left_bottom: Point | None = Field(default=None, alias="LeftBottom")


class Element(TencentModel):
    index: int | None = Field(default=None, alias="Index")
    text: str | None = Field(default=None, alias="Text")
    coord: Polygon | None = Field(default=None, alias="Coord")
    group_type: str | None = Field(default=None, alias="GroupType")
    result_list: list[ResultList] | None = Field(default=None, alias="ResultList")


class ResultList(TencentModel):
    question: list[Element] | None = Field(default=None, alias="Question")
    option: list[Element] | None = Field(default=None, alias="Option")
    figure: list[Element] | None = Field(default=None, alias="Figure")
    table: list[Element] | None = Field(default=None, alias="Table")
    answer: list[Element] | None = Field(default=None, alias="Answer")
    parse: list[Element] | None = Field(default=None, alias="Parse")
    coord: list[Polygon] | None = Field(default=None, alias="Coord")


class QuestionInfo(TencentModel):
    angle: float | None = Field(default=None, alias="Angle")
    height: int | None = Field(default=None, alias="Height")
    width: int | None = Field(default=None, alias="Width")
    result_list: list[ResultList] | None = Field(default=None, alias="ResultList")
    org_height: int | None = Field(default=None, alias="OrgHeight")
    org_width: int | None = Field(default=None, alias="OrgWidth")
    image_base64: str | None = Field(
        default=None,
        alias="ImageBase64",
        repr=False,
        exclude=True,
    )


class Response(TencentModel):
    question_info: list[QuestionInfo] = Field(
        default_factory=list, alias="QuestionInfo"
    )
    request_id: str = Field(alias="RequestId")
