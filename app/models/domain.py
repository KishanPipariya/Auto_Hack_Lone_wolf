import re
from typing import Any, List, Optional

from pydantic import (
    BaseModel,
    Field,
    field_validator,
    model_validator,
)


class Preferences(BaseModel):
    city: Optional[str] = None
    budget: Optional[float] = None
    local_budget: Optional[float] = None
    days: int
    interests: List[str] = Field(default_factory=list)
    vibe: Optional[str] = None
    work_friendly: bool = False
    start_date: Optional[str] = None

    @field_validator("budget", "local_budget")
    @classmethod
    def validate_budget_amount(cls, value: Optional[float]) -> Optional[float]:
        if value is not None and value < 1:
            raise ValueError("Budget amount must be at least 1.")
        return value

    @model_validator(mode="after")
    def validate_single_budget_amount(self) -> "Preferences":
        has_usd_budget = self.budget is not None
        has_local_budget = self.local_budget is not None

        if has_usd_budget == has_local_budget:
            raise ValueError("Submit exactly one of budget or local_budget.")

        if self.local_budget is not None:
            self.budget = self.local_budget

        return self

    @property
    def uses_local_budget(self) -> bool:
        return self.local_budget is not None


class Activity(BaseModel):
    name: str
    cost: float
    duration_hours: float = 1.0
    tags: List[str] = Field(default_factory=list)
    description: str = ""
    image_url: Optional[str] = None
    duration_str: Optional[str] = None

    @field_validator("cost", "duration_hours", mode="before")
    @classmethod
    def parse_number(cls, value: Any) -> float:
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            numbers = re.findall(r"[-+]?\d*\.\d+|\d+", value.replace(",", ""))
            return float(numbers[0]) if numbers else 0.0
        return 0.0


class CostBreakdown(BaseModel):
    transport: float = 0.0
    stay: float = 0.0
    food: float = 0.0
    activities: float = 0.0
    total: float = 0.0
    remaining_budget: float = 0.0

    def calculate_total(self, budget: float | None = None):
        self.total = self.transport + self.stay + self.food + self.activities
        if budget is not None:
            self.remaining_budget = budget - self.total
        return self.total


class DestinationSuggestion(BaseModel):
    city: str
    country: Optional[str] = None
    rationale: Optional[str] = None
    estimated_total_cost: float = 0.0
    tags: List[str] = Field(default_factory=list)


class DayPlan(BaseModel):
    day_number: int
    activities: List[Activity]
    city: Optional[str] = None
    total_cost: float = 0.0

    def calculate_cost(self):
        self.total_cost = sum(float(a.cost) for a in self.activities)
        return self.total_cost


class Itinerary(BaseModel):
    city: str
    recommended_destination: Optional[str] = None
    vibe_rationale: Optional[str] = None
    budget_notes: Optional[str] = None
    work_friendly_notes: Optional[str] = None
    destination_suggestions: List[DestinationSuggestion] = Field(default_factory=list)
    cost_breakdown: CostBreakdown = Field(default_factory=CostBreakdown)
    total_cost: float = 0.0
    uses_local_budget: bool = False
    days: List[DayPlan]
    valid: bool = False
    validation_error: Optional[str] = None

    def calculate_total_cost(self):
        activity_total = sum(day.calculate_cost() for day in self.days)
        if not self.cost_breakdown.activities:
            self.cost_breakdown.activities = activity_total
        self.total_cost = self.cost_breakdown.calculate_total()
        return self.total_cost
