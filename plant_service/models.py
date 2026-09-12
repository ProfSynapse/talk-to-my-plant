from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Readings(StrictModel):
    soil_moisture: float | None = Field(
        default=None, ge=0, le=100,
        description="Calibrated relative index, not volumetric water percent",
    )
    soil_raw: int | None = Field(default=None, ge=0, le=65535)
    temperature_f: float = Field(ge=-40, le=185)
    humidity: float = Field(ge=0, le=100)
    pressure_hpa: float = Field(ge=300, le=1100)
    battery_percent: float = Field(ge=0, le=100)
    battery_voltage: float = Field(ge=0, le=5)

    @model_validator(mode="after")
    def soil_observation(self):
        if self.soil_moisture is None and self.soil_raw is None:
            raise ValueError("soil_moisture or soil_raw is required")
        return self


class Telemetry(StrictModel):
    schema_version: Literal["1.0", "1.1", "1.2"] = "1.2"
    device_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    source: Literal["simulator", "hardware"]
    sensor_placement: Literal["unknown", "bench_air", "foliage_substrate",
                              "orchid_bark"] = "unknown"
    recorded_at: datetime
    readings: Readings
    report_kind: Literal["event", "checkin"] = "event"
    conditions: list[str] = Field(default_factory=list, max_length=10)  # Advisory; recomputed on server.

    @field_validator("recorded_at")
    @classmethod
    def timestamp(cls, value):
        if value.tzinfo is None:
            raise ValueError("recorded_at must include a timezone")
        if (value - datetime.now(timezone.utc)).total_seconds() > 300:
            raise ValueError("recorded_at is too far in the future")
        return value


class Chat(StrictModel):
    request_id: str = Field(min_length=1, max_length=160)
    conversation_id: str = Field(min_length=1, max_length=200)
    device_id: str = Field(default="plant-001", pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    source: Literal["hardware", "simulator"] = "hardware"
    text: str = Field(min_length=1, max_length=4000)


class Care(StrictModel):
    device_id: str = Field(default="plant-001", pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    source: Literal["hardware", "simulator"] = "hardware"
    note: str = Field(min_length=1, max_length=2000)
