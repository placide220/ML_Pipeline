from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class SubMetering(BaseModel):
    kitchen: Optional[float] = Field(None, ge=0)
    laundry: Optional[float] = Field(None, ge=0)
    water_heater_ac: Optional[float] = Field(None, ge=0)


class ReadingCreate(BaseModel):
    reading_ts: datetime
    household_id: int = 1
    global_active_power: float = Field(..., ge=0, description="kW")
    global_reactive_power: Optional[float] = Field(None, ge=0, description="kVAr")
    voltage: Optional[float] = Field(None, ge=150, le=300, description="V")
    global_intensity: Optional[float] = Field(None, ge=0, description="A")
    sub_metering: Optional[SubMetering] = None


class ReadingUpdate(BaseModel):
    """All fields optional (PUT with partial body). The timestamp is the identity, so it cannot change."""
    global_active_power: Optional[float] = Field(None, ge=0)
    global_reactive_power: Optional[float] = Field(None, ge=0)
    voltage: Optional[float] = Field(None, ge=150, le=300)
    global_intensity: Optional[float] = Field(None, ge=0)
    sub_metering: Optional[SubMetering] = None
