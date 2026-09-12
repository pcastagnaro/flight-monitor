from fastapi import APIRouter,Depends,HTTPException
from sqlalchemy import select,desc
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import Search,Offer,Recommendation,SearchRun,PriceSnapshot
from app.schemas import SearchCreate,SearchOut
from app.services.orchestrator import run_search,real_providers
router=APIRouter(prefix="/api")
@router.get("/health")
def health(): return {"ok":True}
@router.get("/providers")
def provider_status():
    return [{"name":p.name,"enabled":p.enabled} for p in real_providers()]
@router.get("/searches")
def searches(db:Session=Depends(get_db)): return db.scalars(select(Search).order_by(Search.id)).all()
@router.post("/searches",response_model=SearchOut)
def create_search(body:SearchCreate,db:Session=Depends(get_db)):
    s=Search(**body.model_dump()); db.add(s); db.commit(); db.refresh(s); return s
@router.post("/searches/{search_id}/run")
async def execute(search_id:int,db:Session=Depends(get_db)):
    s=db.get(Search,search_id)
    if not s: raise HTTPException(404,"Search not found")
    run=await run_search(db,s); return {"run_id":run.id,"status":run.status,"results":run.result_count,"details":run.details}
@router.get("/searches/{search_id}/results")
def results(search_id:int,source:str="real",db:Session=Depends(get_db)):
    if source not in ("real","demo"): raise HTTPException(400,"Invalid source")
    demo=select(PriceSnapshot.id).where(PriceSnapshot.offer_id==Offer.id,PriceSnapshot.provider=="mock").exists()
    offers=db.scalars(select(Offer).where(Offer.search_id==search_id,demo if source=="demo" else ~demo).order_by(Offer.best_price).limit(100)).all(); out=[]
    for o in offers:
        rec=db.scalar(select(Recommendation).where(Recommendation.offer_id==o.id).order_by(desc(Recommendation.created_at)).limit(1)); out.append({"source":source,"last_seen_at":o.last_seen_at,"id":o.id,"origin":o.origin,"destination":o.destination,"departure_date":o.departure_date,"return_date":o.return_date,"price":float(o.best_price),"currency":o.currency,"airlines":o.airlines,"stops":o.stops,"duration_minutes":o.duration_minutes,"providers":o.provider_count,"consensus":o.consensus_score,"price_level":o.price_level,"booking_url":o.booking_url,"recommendation":None if source=="demo" or not rec else {"state":rec.state,"score":rec.score,"confidence":rec.confidence,"reasons":rec.reasons,"percentile":rec.historical_percentile}})
    return out
@router.get("/searches/{search_id}/runs")
def runs(search_id:int,db:Session=Depends(get_db)): return db.scalars(select(SearchRun).where(SearchRun.search_id==search_id).order_by(desc(SearchRun.started_at)).limit(20)).all()
