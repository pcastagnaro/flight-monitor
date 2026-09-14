from sqlalchemy import (
    String,
    Integer,
    Boolean,
    Date,
    DateTime,
    Numeric,
    Float,
    ForeignKey,
    JSON,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base


class Search(Base):
    __tablename__ = "searches"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    origin: Mapped[str] = mapped_column(String(3))
    destinations: Mapped[list] = mapped_column(JSON)
    departure_from: Mapped[object] = mapped_column(Date)
    departure_to: Mapped[object] = mapped_column(Date)
    return_from: Mapped[object] = mapped_column(Date)
    return_to: Mapped[object] = mapped_column(Date)
    adults: Mapped[int] = mapped_column(Integer, default=1)
    cabin: Mapped[str] = mapped_column(String(20), default="economy")
    max_stops: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_price: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    ideal_price: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    max_price: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    currency: Mapped[str] = mapped_column(
        String(3), default="EUR", server_default="EUR"
    )
    min_nights: Mapped[int] = mapped_column(default=1, server_default="1")
    max_nights: Mapped[int] = mapped_column(default=365, server_default="365")
    max_duration_minutes: Mapped[int | None] = mapped_column(nullable=True)
    airlines: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    strategy: Mapped[str] = mapped_column(
        String(20), default="waterfall", server_default="waterfall"
    )
    provider_names: Mapped[list] = mapped_column(
        JSON, default=list, server_default="[]"
    )
    max_combinations: Mapped[int] = mapped_column(default=12, server_default="12")
    max_provider_calls: Mapped[int] = mapped_column(default=30, server_default="30")
    require_complete_trip: Mapped[bool] = mapped_column(
        default=False, server_default="false"
    )
    allow_experimental: Mapped[bool] = mapped_column(
        default=False, server_default="false"
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[object] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class SearchRun(Base):
    __tablename__ = "search_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    search_id: Mapped[int] = mapped_column(
        ForeignKey("searches.id", ondelete="CASCADE")
    )
    started_at: Mapped[object] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    finished_at: Mapped[object | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    provider_count: Mapped[int] = mapped_column(default=0)
    result_count: Mapped[int] = mapped_column(default=0)
    status: Mapped[str] = mapped_column(String(20), default="running")
    details: Mapped[dict] = mapped_column(JSON, default=dict)


class Offer(Base):
    __tablename__ = "offers"
    __table_args__ = (
        UniqueConstraint(
            "search_id", "fingerprint", name="uq_search_offer_fingerprint"
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    search_id: Mapped[int] = mapped_column(
        ForeignKey("searches.id", ondelete="CASCADE")
    )
    fingerprint: Mapped[str] = mapped_column(String(64))
    origin: Mapped[str] = mapped_column(String(3))
    destination: Mapped[str] = mapped_column(String(3))
    departure_date: Mapped[object] = mapped_column(Date)
    return_date: Mapped[object] = mapped_column(Date)
    airlines: Mapped[list] = mapped_column(JSON, default=list)
    stops: Mapped[int | None] = mapped_column(nullable=True)
    duration_minutes: Mapped[int | None] = mapped_column(nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    best_price: Mapped[float] = mapped_column(Numeric(10, 2))
    median_provider_price: Mapped[float | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    provider_count: Mapped[int] = mapped_column(default=1)
    consensus_score: Mapped[float] = mapped_column(Float, default=0.0)
    price_level: Mapped[str | None] = mapped_column(String(20), nullable=True)
    booking_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_seen_at: Mapped[object] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class PriceSnapshot(Base):
    __tablename__ = "price_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    offer_id: Mapped[int] = mapped_column(ForeignKey("offers.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(40))
    provider_offer_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    price: Mapped[float] = mapped_column(Numeric(10, 2))
    currency: Mapped[str] = mapped_column(String(3))
    booking_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw: Mapped[dict] = mapped_column(JSON)
    checked_at: Mapped[object] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Recommendation(Base):
    __tablename__ = "recommendations"
    id: Mapped[int] = mapped_column(primary_key=True)
    offer_id: Mapped[int] = mapped_column(ForeignKey("offers.id", ondelete="CASCADE"))
    state: Mapped[str] = mapped_column(String(10))
    score: Mapped[float] = mapped_column(Float)
    historical_percentile: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[float] = mapped_column(Float)
    reasons: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[object] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ProviderState(Base):
    __tablename__ = "provider_states"
    name: Mapped[str] = mapped_column(String(40), primary_key=True)
    month: Mapped[str] = mapped_column(String(7))
    calls: Mapped[int] = mapped_column(default=0)
    failures: Mapped[int] = mapped_column(default=0)
    blocked_until: Mapped[object | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(String(100), nullable=True)


class QueryCache(Base):
    __tablename__ = "query_cache"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider: Mapped[str] = mapped_column(String(40))
    payload: Mapped[list] = mapped_column(JSON)
    expires_at: Mapped[object] = mapped_column(DateTime(timezone=True), index=True)
    observed_at: Mapped[object] = mapped_column(DateTime(timezone=True))
