from datetime import date
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator

PROVIDER_NAMES = {
    "flightpowers",
    "serpapi",
    "travelpayouts",
    "datacrawler",
    "amadeus",
    "kiwi",
    "ryanair",
    "flightfinder",
    "fast_flights",
    "google_browser",
}


class SearchCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    name: str = Field("Mi viaje", min_length=1, max_length=120)
    origin: str = Field("BCN", pattern=r"^[A-Z]{3}$")
    destinations: list[str] = Field(
        default_factory=lambda: ["EZE"], min_length=1, max_length=8
    )
    departure_from: date
    departure_to: date
    return_from: date
    return_to: date
    adults: int = Field(1, ge=1, le=9)
    cabin: Literal["economy", "premium_economy", "business", "first"] = "economy"
    currency: Literal["EUR", "USD", "GBP"] = "EUR"
    max_stops: int | None = Field(1, ge=0, le=3)
    target_price: float | None = Field(None, gt=0)
    ideal_price: float | None = Field(None, gt=0)
    max_price: float | None = Field(None, gt=0)
    min_nights: int = Field(1, ge=1, le=365)
    max_nights: int = Field(365, ge=1, le=365)
    max_duration_minutes: int | None = Field(None, ge=30, le=5760)
    airlines: list[str] = Field(default_factory=list, max_length=20)
    strategy: Literal["waterfall", "exhaustive"] = "waterfall"
    provider_names: list[str] = Field(default_factory=list, max_length=10)
    max_combinations: int = Field(12, ge=1, le=120)
    max_provider_calls: int = Field(30, ge=1, le=300)
    allow_experimental: bool = False
    require_complete_trip: bool = False
    active: bool = True

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("origin", mode="before")
    @classmethod
    def normalize_origin(cls, value):
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("destinations")
    @classmethod
    def airports(cls, values):
        import re

        values = list(dict.fromkeys(v.strip().upper() for v in values))
        if any(not re.fullmatch(r"[A-Z]{3}", v) for v in values):
            raise ValueError("Usa códigos IATA de tres letras")
        return values

    @field_validator("provider_names")
    @classmethod
    def known_providers(cls, values):
        if set(values) - PROVIDER_NAMES:
            raise ValueError("Proveedor desconocido")
        return list(dict.fromkeys(values))

    @model_validator(mode="after")
    def validate_trip(self):
        if self.departure_from > self.departure_to or self.return_from > self.return_to:
            raise ValueError("Rangos de fechas invertidos")
        if (self.departure_to - self.departure_from).days > 90 or (
            self.return_to - self.return_from
        ).days > 90:
            raise ValueError("Cada rango puede cubrir como máximo 91 días")
        if self.min_nights > self.max_nights:
            raise ValueError("Estancia mínima mayor que máxima")
        if self.return_to <= self.departure_from or self.origin in self.destinations:
            raise ValueError("Ruta o regreso inválido")
        if (self.return_to - self.departure_from).days < self.min_nights or (
            self.return_from - self.departure_to
        ).days > self.max_nights:
            raise ValueError("No existen fechas con esa estancia")
        prices = [
            v
            for v in (self.ideal_price, self.target_price, self.max_price)
            if v is not None
        ]
        if prices != sorted(prices):
            raise ValueError("Los precios deben cumplir ideal ≤ objetivo ≤ máximo")
        return self


class SearchOut(SearchCreate):
    id: int
    model_config = ConfigDict(from_attributes=True)
