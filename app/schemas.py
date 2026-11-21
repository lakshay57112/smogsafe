"""Request/response models. Pydantic validates every input before it reaches a service."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

Mode = Literal[
    "car_solo", "car_pool", "cab", "auto", "two_wheeler", "e_two_wheeler",
    "bus", "metro", "walk_cycle", "work_from_home",
]
AgeGroup = Literal["infant", "child", "teen", "adult", "senior"]
Condition = Literal["asthma", "copd", "heart", "diabetes", "pregnant", "allergies"]
Language = Literal["en", "hi", "hinglish"]
Activity = Literal["rest", "light", "moderate", "vigorous"]
Setting = Literal["outdoors", "indoors_windows_open", "indoors_windows_closed", "indoors_with_purifier"]
Mask = Literal["none", "cloth", "surgical", "n95"]


def _clean_text(value: str) -> str:
    # Strip control characters and collapse whitespace.
    return " ".join("".join(ch for ch in value if ch.isprintable()).split())


class Member(BaseModel):
    id: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=40)
    age_group: AgeGroup = "adult"
    conditions: list[Condition] = Field(default_factory=list, max_length=6)
    outdoor_time: Literal["low", "medium", "high"] = "medium"

    @field_validator("name")
    @classmethod
    def clean_name(cls, v: str) -> str:
        return _clean_text(v) or "Member"


class Household(BaseModel):
    members: list[Member] = Field(default_factory=list, max_length=10)
    commute_mode: Mode = "metro"
    commute_km: float = Field(default=8, ge=0, le=150)
    commute_days: int = Field(default=5, ge=0, le=7)
    cooking_fuel: Literal["lpg", "png", "electric", "biomass", "kerosene"] = "lpg"
    has_purifier: bool = False
    near_busy_road: bool = False
    exercises_outdoors: bool = False


class Location(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    place_name: str = Field(default="your area", max_length=80)

    @field_validator("place_name")
    @classmethod
    def clean_place(cls, v: str) -> str:
        return _clean_text(v) or "your area"


class PlanRequest(Location):
    household: Household = Field(default_factory=Household)
    language: Language = "en"


class ChatTurn(BaseModel):
    role: Literal["user", "model"]
    text: str = Field(min_length=1, max_length=2000)


class AskRequest(Location):
    question: str = Field(min_length=2, max_length=500)
    household: Household | None = None
    history: list[ChatTurn] = Field(default_factory=list, max_length=8)
    language: Language = "en"

    @field_validator("question")
    @classmethod
    def clean_question(cls, v: str) -> str:
        v = _clean_text(v)
        if len(v) < 2:
            raise ValueError("Question is too short")
        return v


class ExposureRequest(BaseModel):
    pm25: float = Field(ge=0, le=2000)
    minutes: float = Field(gt=0, le=24 * 60)
    activity: Activity = "light"
    from_setting: Setting = "outdoors"
    to_setting: Setting = "indoors_windows_closed"
    from_mask: Mask = "none"
    to_mask: Mask = "none"


class CommuteRequest(BaseModel):
    from_mode: Mode = "car_solo"
    to_mode: Mode = "metro"
    km_one_way: float = Field(default=10, gt=0, le=150)
    days_per_week: int = Field(default=5, ge=1, le=7)


class PledgeRequest(BaseModel):
    city: str = Field(min_length=2, max_length=80)
    pledge_id: str = Field(min_length=2, max_length=40)
    device_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9-]+$")

    @field_validator("city")
    @classmethod
    def clean_city(cls, v: str) -> str:
        v = _clean_text(v)
        if len(v) < 2:
            raise ValueError("City is too short")
        return v


# --- Shape Gemini must return for the daily plan (used as response_schema) ---

ImpactKey = Literal[
    "skip_outdoor_exercise", "shift_to_clean_hours", "wear_n95", "close_windows", "use_purifier",
    "commute_switch", "avoid_incense", "avoid_burning", "clean_cooking", "none",
]


class AIAction(BaseModel):
    time: Literal["Morning", "Afternoon", "Evening", "Night", "Anytime"]
    category: Literal["commute", "outdoor", "indoor", "cooking", "health", "community"]
    title: str
    detail: str
    why: str
    impact_key: ImpactKey


class AIMemberAdvice(BaseModel):
    member_id: str
    advice: list[str]


class AIChecklistItem(BaseModel):
    item: str
    why: str


class AISwap(BaseModel):
    swap_from: str
    swap_to: str
    why: str


class AIPlan(BaseModel):
    headline: str
    summary: str
    actions: list[AIAction]
    family: list[AIMemberAdvice]
    indoor_checklist: list[AIChecklistItem]
    swaps: list[AISwap]
