from pydantic import BaseModel, Field
from typing import Optional, List

class PlannerRequest(BaseModel):
    rowid: Optional[int] = None  # If querying an existing survey respondent
    orig_lat: Optional[float] = None
    orig_lon: Optional[float] = None
    dest_lat: Optional[float] = None
    dest_lon: Optional[float] = None
    transport_mode: Optional[str] = "public_transport"
    trips_per_week: float = 10.0 # Round-trip 5 days/wk = 10 trips
    ev_monthly_loan: Optional[float] = None # Custom loan override


class SurveySubmission(BaseModel):
    payload: dict = Field(default_factory=dict)

class PublicTransport(BaseModel):
    orig_lat: Optional[float] = None
    orig_lon: Optional[float] = None
    dest_lat: Optional[float] = None
    dest_lon: Optional[float] = None
    trips_per_week: float = 10.0

class ModeOption(BaseModel):
    option_name: str
    monthly_cost_vnd: float
    one_way_duration_mins: float
    monthly_time_spent_hours: float
    monthly_co2_kg: float
    cost_breakdown: dict

class PlannerResponse(BaseModel):
    origin: str
    destination: str
    one_way_distance_km: float
    trips_per_week: float
    driving_polyline: Optional[str] = None
    transit_polyline: Optional[str] = None
    options: List[ModeOption]