from typing import List, Optional, Union
from pydantic import BaseModel, Field, ConfigDict


class Preferences(BaseModel):
    city: str
    budget: float
    days: int
    interests: List[str] = Field(default_factory=list)


class Activity(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    
    name: str
    cost: Union[float, str]
    duration_hours: Union[float, str] = Field(alias="duration")
    tags: List[str]
    description: str
    image_url: Optional[str] = None


class DayPlan(BaseModel):
    day_number: int
    activities: List[Activity]
    total_cost: float = 0.0

    def calculate_cost(self):
        self.total_cost = sum(a.cost for a in self.activities)
        return self.total_cost


class Itinerary(BaseModel):
    city: str
    total_cost: float = 0.0
    days: List[DayPlan]
    valid: bool = False
    validation_error: Optional[str] = None

    def calculate_total_cost(self):
        self.total_cost = sum(day.calculate_cost() for day in self.days)
        return self.total_cost
