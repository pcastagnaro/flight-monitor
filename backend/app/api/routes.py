from fastapi import APIRouter, Depends, HTTPException, Query as Param
from sqlalchemy import select, desc
from collections import defaultdict
from datetime import timedelta
from app.services.history import history_indicator
from typing import Annotated
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import Search, Offer, Recommendation, SearchRun, PriceSnapshot
from app.schemas import SearchCreate, SearchOut
from app.services.orchestrator import run_search, real_providers, SearchBusy
from app.services.planner import plan
from app.services.resilience import EXPERIMENTAL, FAMILIES, ORDER, integer_env, utc
from app.models import ProviderState
from datetime import datetime, timezone
from urllib.parse import urlparse

router = APIRouter(prefix="/api")


@router.get("/health")
def health():
    return {"ok": True}


@router.get("/providers")
def provider_status(db: Session = Depends(get_db)):
    out = []
    for p in sorted(real_providers(), key=lambda p: ORDER.index(p.name)):
        state = db.get(ProviderState, p.name)
        out.append(
            {
                "name": p.name,
                "enabled": p.enabled,
                "family": FAMILIES[p.name],
                "experimental": p.name in EXPERIMENTAL,
                "monthly_calls": state.calls
                if state and state.month == datetime.now(timezone.utc).strftime("%Y-%m")
                else 0,
                "monthly_limit": integer_env(
                    p.name.upper() + "_MONTHLY_CALL_LIMIT",
                    integer_env("PROVIDER_MONTHLY_CALL_LIMIT", 500),
                ),
                "blocked_until": state.blocked_until
                if state
                and state.blocked_until
                and utc(state.blocked_until) > datetime.now(timezone.utc)
                else None,
                "last_error": state.last_error if state else None,
                "notes": {
                    "flightfinder": "Solo USD; requiere dependencia opcional",
                    "ryanair": "Solo 1 adulto, economy; dos tarifas separadas",
                    "travelpayouts": "Referencia cacheada; 1 adulto, economy",
                    "flightpowers": "1 adulto, economy",
                    "amadeus": "Producción"
                    if getattr(p, "production", False)
                    else "Entorno de prueba: resultados en Demostración",
                    "fast_flights": "Requiere dependencia opcional; regreso sin verificar",
                    "google_browser": "Último recurso: Chromium local; requiere imagen con navegador",
                }.get(p.name, "Descubrimiento de precios"),
            }
        )
    return out


@router.get("/searches")
def searches(db: Session = Depends(get_db)):
    return db.scalars(select(Search).order_by(Search.id)).all()


@router.post("/searches", response_model=SearchOut)
def create_search(body: SearchCreate, db: Session = Depends(get_db)):
    s = Search(**body.model_dump())
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


@router.post("/searches/{search_id}/run")
async def execute(search_id: int, db: Session = Depends(get_db)):
    s = db.get(Search, search_id)
    if not s:
        raise HTTPException(404, "Search not found")
    try:
        run = await run_search(db, s)
    except SearchBusy:
        raise HTTPException(409, "Ya hay una búsqueda en curso. Espera a que termine.")
    except Exception:
        raise HTTPException(500, "La ejecución falló; consulta su diagnóstico.")
    return {
        "run_id": run.id,
        "status": run.status,
        "results": run.result_count,
        "details": run.details,
    }


@router.get("/searches/{search_id}/results")
def results(
    search_id: int,
    source: str = "real",
    db: Session = Depends(get_db),
    max_price: Annotated[float | None, Param(gt=0, allow_inf_nan=False)] = None,
    max_stops: Annotated[int | None, Param(ge=0, le=3)] = None,
    airline: Annotated[str | None, Param(max_length=100)] = None,
    destination: Annotated[str | None, Param(pattern=r"^[a-zA-Z]{3}$")] = None,
    min_price: Annotated[float | None, Param(ge=0, allow_inf_nan=False)] = None,
    max_duration: Annotated[int | None, Param(gt=0)] = None,
    provider: Annotated[str | None, Param(max_length=40)] = None,
    fresh_only: bool = False,
    direction: str | None = None,
    limit: int = 100,
    offset: int = 0,
    sort: str = "price",
):
    if source not in ("real", "demo"):
        raise HTTPException(400, "Invalid source")
    demo = (
        select(PriceSnapshot.id)
        .where(
            PriceSnapshot.offer_id == Offer.id,
            (
                (PriceSnapshot.provider == "mock")
                | (PriceSnapshot.raw["_environment"].as_string() == "test")
            ),
        )
        .exists()
    )
    if direction not in (None, "asc", "desc"):
        raise HTTPException(400, "Dirección inválida")
    if min_price is not None and max_price is not None and min_price > max_price:
        raise HTTPException(400, "El precio mínimo supera al máximo")
    if sort not in (
        "price",
        "duration",
        "recent",
        "destination",
        "departure",
        "return",
        "stops",
        "airline",
    ):
        raise HTTPException(400, "Orden inválido")
    if not 1 <= limit <= 500 or offset < 0 or offset > 10000:
        raise HTTPException(400, "Paginación inválida")
    statement = select(Offer).where(
        Offer.search_id == search_id, demo if source == "demo" else ~demo
    )
    if min_price is not None:
        statement = statement.where(Offer.best_price >= min_price)
    if max_duration is not None:
        statement = statement.where(Offer.duration_minutes <= max_duration)
    if provider:
        statement = statement.where(
            select(PriceSnapshot.id)
            .where(
                PriceSnapshot.offer_id == Offer.id, PriceSnapshot.provider == provider
            )
            .exists()
        )
    if max_price is not None:
        statement = statement.where(Offer.best_price <= max_price)
    if max_stops is not None:
        statement = statement.where(Offer.stops <= max_stops)
    if destination:
        statement = statement.where(Offer.destination == destination.upper())
    if fresh_only:
        statement = statement.where(
            Offer.last_seen_at >= datetime.now(timezone.utc) - timedelta(hours=6)
        )
    if airline:
        from sqlalchemy import cast, String

        statement = statement.where(
            cast(Offer.airlines, String).ilike(
                "%" + airline.replace("%", "").replace("_", "") + "%"
            )
        )
    from sqlalchemy import cast, String

    column = {
        "price": Offer.best_price,
        "duration": Offer.duration_minutes,
        "recent": Offer.last_seen_at,
        "destination": Offer.destination,
        "departure": Offer.departure_date,
        "return": Offer.return_date,
        "stops": Offer.stops,
        "airline": cast(Offer.airlines, String),
    }[sort]
    descending = direction == "desc" or (direction is None and sort == "recent")
    ordering = (column.desc() if descending else column.asc()).nulls_last()
    offers = db.scalars(
        statement.order_by(ordering, Offer.id).offset(offset).limit(limit)
    ).all()
    historical = defaultdict(list)
    if offers:
        cutoff = min(utc(o.last_seen_at) for o in offers) - timedelta(days=30)
        for snapshot in db.scalars(select(PriceSnapshot).where(
            PriceSnapshot.offer_id.in_([o.id for o in offers]),
            PriceSnapshot.checked_at >= cutoff,
        )):
            historical[snapshot.offer_id].append(snapshot)
    out = []
    for o in offers:
        rec = db.scalar(
            select(Recommendation)
            .where(Recommendation.offer_id == o.id)
            .order_by(desc(Recommendation.created_at), desc(Recommendation.id))
            .limit(1)
        )
        out.append(
            {
                "source": source,
                "last_seen_at": o.last_seen_at,
                "id": o.id,
                "origin": o.origin,
                "destination": o.destination,
                "departure_date": o.departure_date,
                "return_date": o.return_date,
                "price": float(o.best_price),
                "currency": o.currency,
                "airlines": o.airlines,
                "stops": o.stops,
                "duration_minutes": o.duration_minutes,
                "providers": o.provider_count,
                "consensus": o.consensus_score,
                "price_level": o.price_level,
                "history_indicator": history_indicator(o, historical[o.id]),
                "booking_url": o.booking_url
                if o.booking_url and urlparse(o.booking_url).scheme in ("http", "https")
                else None,
                "recommendation": None
                if source == "demo" or not rec
                else {
                    "state": rec.state,
                    "score": rec.score,
                    "confidence": rec.confidence,
                    "reasons": rec.reasons,
                    "percentile": rec.historical_percentile,
                },
            }
        )
        snapshots = db.scalars(
            select(PriceSnapshot)
            .where(PriceSnapshot.offer_id == o.id)
            .order_by(PriceSnapshot.checked_at.desc())
            .limit(10)
        ).all()
        newest = snapshots[0] if snapshots else None
        out[-1].update(
            {
                "provider_names": list(dict.fromkeys(x.provider for x in snapshots)),
                "complete_trip": bool(newest and newest.raw.get("_complete_trip")),
                "stale": (
                    datetime.now(timezone.utc) - utc(o.last_seen_at)
                ).total_seconds()
                > 21600,
                "quality": (
                    newest.raw.get("_quality")
                    or (
                        "reference"
                        if newest.provider == "travelpayouts"
                        else "discovery"
                    )
                )
                if newest
                else "unknown",
                "environment": newest.raw.get("_environment") if newest else None,
            }
        )
    return out


@router.get("/searches/{search_id}/runs")
def runs(search_id: int, db: Session = Depends(get_db)):
    return db.scalars(
        select(SearchRun)
        .where(SearchRun.search_id == search_id)
        .order_by(desc(SearchRun.started_at), desc(SearchRun.id))
        .limit(20)
    ).all()


@router.post("/searches/preview")
def preview(body: SearchCreate):
    queries, total = plan(body)
    return {
        "total_combinations": total,
        "planned_combinations": len(queries),
        "omitted_combinations": total - len(queries),
        "max_provider_calls": body.max_provider_calls,
        "strategy": body.strategy,
        "dates": [
            {
                "destination": q.destination,
                "departure": q.departure_date,
                "return": q.return_date,
            }
            for q in queries
        ],
    }


@router.patch("/searches/{search_id}/active")
def toggle(search_id: int, active: bool, db: Session = Depends(get_db)):
    search = db.get(Search, search_id)
    if not search:
        raise HTTPException(404, "Search not found")
    search.active = active
    db.commit()
    return {"id": search.id, "active": search.active}


@router.get("/offers/{offer_id}/history")
def history(offer_id: int, db: Session = Depends(get_db)):
    if not db.get(Offer, offer_id):
        raise HTTPException(404, "Offer not found")
    rows = db.scalars(
        select(PriceSnapshot)
        .where(PriceSnapshot.offer_id == offer_id)
        .order_by(PriceSnapshot.checked_at.desc())
        .limit(100)
    ).all()
    return [
        {
            "price": float(x.price),
            "currency": x.currency,
            "provider": x.provider,
            "checked_at": x.checked_at,
        }
        for x in rows
    ]
