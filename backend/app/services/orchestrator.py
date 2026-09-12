import asyncio,hashlib,statistics
import httpx
from collections import defaultdict
from datetime import datetime,timezone,timedelta
from sqlalchemy import select
from app.models import Offer,PriceSnapshot,SearchRun,Recommendation
from app.providers.base import Query
from app.providers.flightpowers import FlightPowersProvider
from app.providers.serpapi import SerpApiProvider
from app.providers.travelpayouts import TravelpayoutsProvider
from app.providers.mock import MockProvider
from app.providers.datacrawler import DataCrawlerProvider
from .scoring import score_offer
from .telegram import send_telegram

def _fp(o):
    airline="|".join(sorted(a.lower().replace(" ","") for a in o.airlines if a)); key=f"{o.origin}|{o.destination}|{o.departure_date}|{o.return_date}|{airline}|{o.stops}"; return hashlib.sha256(key.encode()).hexdigest()
def real_providers():
    return [FlightPowersProvider(),SerpApiProvider(),TravelpayoutsProvider(),DataCrawlerProvider()]
def providers():
    return [p for p in real_providers() if p.enabled] or [MockProvider()]
async def _safe(p,q):
    try: return p.name,await p.search(q),None
    except httpx.HTTPStatusError as e: return p.name,[],f"HTTP {e.response.status_code}"
    except Exception as e: return p.name,[],type(e).__name__
async def search_query_parallel(q, selected=None): return await asyncio.gather(*[_safe(p,q) for p in (providers() if selected is None else selected)])
def merge(items):
    groups=defaultdict(list)
    for x in items: groups[_fp(x)].append(x)
    out=[]
    for fp,xs in groups.items():
        prices=[x.price for x in xs]; med=statistics.median(prices); spread=(max(prices)-min(prices))/med if med else 1; pc=len({x.provider for x in xs}); live=len({x.provider for x in xs if x.live}); agreement=max(0,1-min(spread,.30)/.30); consensus=round(100*(.55*min(1,pc/2)+.45*agreement),1); best=min(xs,key=lambda x:x.price); out.append((fp,best,xs,med,consensus,live))
    return out
async def run_search(db,search):
    run=SearchRun(search_id=search.id,status="running",details={}); db.add(run); db.commit(); db.refresh(run)
    qs=[]; d=search.departure_from
    while d<=search.departure_to:
        r=search.return_from
        while r<=search.return_to:
            for dest in search.destinations: qs.append(Query(search.origin,dest,d,r,search.adults,search.cabin,search.max_stops))
            r+=timedelta(days=1)
        d+=timedelta(days=1)
    selected=providers()
    sem=asyncio.Semaphore(8)
    async def one(q):
        async with sem: return await search_query_parallel(q, selected)
    batches=await asyncio.gather(*[one(q) for q in qs]); items=[]; errs={}; pnames=set()
    for b in batches:
        for pn,offers,err in b:
            pnames.add(pn); items.extend(offers)
            if err: errs.setdefault(pn,[]).append(err)
    for fp,best,xs,med,consensus,live_count in merge(items):
        o=db.scalar(select(Offer).where(Offer.search_id==search.id,Offer.fingerprint==fp))
        if not o:
            o=Offer(search_id=search.id,fingerprint=fp,origin=best.origin,destination=best.destination,departure_date=best.departure_date,return_date=best.return_date,airlines=best.airlines,stops=best.stops,duration_minutes=best.duration_minutes,currency=best.currency,best_price=best.price,median_provider_price=med,provider_count=len({x.provider for x in xs}),consensus_score=consensus,price_level=best.price_level,booking_url=best.booking_url); db.add(o); db.flush()
        else:
            o.best_price=best.price; o.median_provider_price=med; o.provider_count=len({x.provider for x in xs}); o.consensus_score=consensus; o.price_level=best.price_level or o.price_level; o.booking_url=best.booking_url or o.booking_url; o.last_seen_at=datetime.now(timezone.utc)
        for x in xs: db.add(PriceSnapshot(offer_id=o.id,provider=x.provider,provider_offer_id=x.provider_offer_id,price=x.price,currency=x.currency,booking_url=x.booking_url,raw=x.raw))
        previous=db.scalar(select(Recommendation).where(Recommendation.offer_id==o.id).order_by(Recommendation.created_at.desc()).limit(1))
        state,total,confidence,reasons,pct=score_offer(db,o,search,live_count)
        db.add(Recommendation(offer_id=o.id,state=state,score=total,historical_percentile=pct,confidence=confidence,reasons=reasons))
        if best.provider!="mock" and state=="BUY" and (previous is None or previous.state!="BUY"):
            await send_telegram(f"✈️ BUY · {o.origin}→{o.destination} · {o.departure_date} / {o.return_date} · €{float(o.best_price):.0f} · score {total} · confianza {confidence}%")
    run.provider_count=len(pnames); run.result_count=len(items); run.status="ok" if items else "empty"; run.finished_at=datetime.now(timezone.utc); run.details={"mode":"demo" if all(p.name=="mock" for p in selected) else "real","providers":{p.name:{"enabled":p.enabled,"results":sum(x.provider==p.name for x in items),"errors":len(errs.get(p.name,[]))} for p in real_providers()},"provider_errors":{k:v[:3] for k,v in errs.items()},"combinations":len(qs),"provider_usage":{p.name:{"requests":p.requests,"skipped":p.skipped,"limit_per_run":p.limit} for p in selected if isinstance(p,DataCrawlerProvider)}}; db.commit(); return run
