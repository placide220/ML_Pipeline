from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class SubMetering(BaseModel):
    kitchen: Optional[float] = Field(None, ge=0)
    laundry: Optional[float] = Field(None, ge=0)
    water_heater_ac: Optional[float] = Field(None, ge=0)


class ReadingCreate(BaseModel):
    reading_ts: datetime
    household_id: str = "SCEAUX-01"          # household code
    global_active_power_kw: float = Field(..., ge=0)
    global_reactive_power_kvar: float = Field(..., ge=0)
    voltage_v: float = Field(..., ge=150, le=300)
    global_intensity_a: float = Field(..., ge=0)
    sub_metering_wh: Optional[SubMetering] = None


class ReadingUpdate(BaseModel):
    """Partial update. The timestamp identifies the record, so it cannot be changed."""
    global_active_power_kw: Optional[float] = Field(None, ge=0)
    global_reactive_power_kvar: Optional[float] = Field(None, ge=0)
    voltage_v: Optional[float] = Field(None, ge=150, le=300)
    global_intensity_a: Optional[float] = Field(None, ge=0)
    sub_metering_wh: Optional[SubMetering] = None
