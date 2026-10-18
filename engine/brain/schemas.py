"""What each brain task returns."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ..models import Question
from ..timeline import Timeline


class AnalyseResult(BaseModel):
    questions: list[Question] = Field(default_factory=list, max_length=8)
    assumptions: list[str] = Field(default_factory=list, description="what will be assumed for non-blocking gaps")
    ready: bool = Field(description="true when no blocking question is left")


class PlanResult(BaseModel):
    timeline: Timeline
    summary: str = Field("", description="2-3 sentences for the creator")
    changes: list[str] = Field(default_factory=list, description="what changed (from the draft / for each note)")


class ClipMatch(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    phrase: str = Field(description="1-4 consecutive words exactly as in the transcript")
    src: str = Field(description="clip path from the input")
    said_at: float | None = Field(None, description="seconds into the voiceover where the phrase starts")
    in_: float | None = Field(None, alias="in", description="optional source second to start the clip from")
    reason: str
    confidence: Literal["low", "medium", "high"] = "medium"


class ClipMatchResult(BaseModel):
    matches: list[ClipMatch] = Field(default_factory=list)
    unmatched: list[str] = Field(default_factory=list, description="clips left for the software to place")
    notes: list[str] = Field(default_factory=list)
