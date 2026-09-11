from sqlalchemy import select
from app.models import PriceSnapshot

def score_offer(db,offer,search,live_count:int):
    history=[float(x) for x in db.scalars(select(PriceSnapshot.price).where(PriceSnapshot.offer_id==offer.id).order_by(PriceSnapshot.checked_at)).all()]
    price=float(offer.best_price); percentile=None; history_score=50.0
    if len(history)>=5:
        percentile=round(100*sum(1 for x in history if x<=price)/len(history),1); history_score=max(0,100-percentile)
    target_score=50.0
    if search.ideal_price and price<=float(search.ideal_price): target_score=100
    elif search.target_price and price<=float(search.target_price): target_score=90
    elif search.max_price and price>float(search.max_price): target_score=0
    elif search.target_price:
        target_score=max(0,80-max(0,price/float(search.target_price)-1)*200)
    insight_score={"low":100,"typical":60,"high":15}.get((offer.price_level or "").lower(),50)
    itinerary_score=100-(min(45,(offer.stops or 0)*20))
    if offer.duration_minutes: itinerary_score-=max(0,min(25,(offer.duration_minutes-900)/20))
    consensus=float(offer.consensus_score); confidence=min(100.0,20+consensus*.55+live_count*20)
    total=round(.30*target_score+.25*history_score+.20*insight_score+.10*itinerary_score+.15*consensus,1)
    reasons=[f"Consensus {offer.provider_count} provider(s): {consensus:.0f}%"]
    if offer.price_level: reasons.insert(0,f"Market price level: {offer.price_level}")
    if percentile is not None: reasons.append(f"Own-history percentile: {percentile:.0f}")
    if search.target_price: reasons.append(f"Target €{float(search.target_price):.0f}; current €{price:.0f}")
    state="BUY" if total>=82 and confidence>=60 and live_count>=1 else "WATCH" if total>=65 else "WAIT"
    return state,total,round(confidence,1),reasons,percentile
