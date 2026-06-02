from typing import List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


class Preferences(BaseModel):
    city: Optional[str] = None
    budget: float
    days: int
    interests: List[str] = Field(default_factory=list)
    vibe: Optional[str] = None
    work_friendly: bool = False
    start_date: Optional[str] = None


class Activity(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str
    cost: Union[float, str]
    duration_hours: Union[float, str] = Field(alias="duration")
    tags: List[str]
    description: str
    image_url: Optional[str] = None
    duration_str: Optional[str] = None


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
        self.total_cost = sum(a.cost for a in self.activities)
        return self.total_cost


class Itinerary(BaseModel):
    city: str
    recommended_destination: Optional[str] = None
    vibe_rationale: Optional[str] = None
    budget_notes: Optional[str] = None
    work_friendly_notes: Optional[str] = None
    cost_breakdown: CostBreakdown = Field(default_factory=CostBreakdown)
    total_cost: float = 0.0
    days: List[DayPlan]
    valid: bool = False
    validation_error: Optional[str] = None

    def calculate_total_cost(self):
        activity_total = sum(day.calculate_cost() for day in self.days)
        if not self.cost_breakdown.activities:
            self.cost_breakdown.activities = activity_total
        self.total_cost = self.cost_breakdown.calculate_total()
        return self.total_cost
