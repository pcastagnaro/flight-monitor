import os,httpx
from .base import Query,ProviderOffer
class FlightPowersProvider:
    name="flightpowers"
    def __init__(self): self.key=os.getenv("FLIGHTPOWERS_API_KEY","")
    @property
    def enabled(self): return bool(self.key)
    async def search(self,q:Query):
        payload={"from_airport":q.origin,"to_airport":q.destination,"departure_date":q.departure_date.isoformat(),"return_date":q.return_date.isoformat(),"currency":q.currency.lower(),"limit":15}
        if q.max_stops is not None: payload["max_stops"]=q.max_stops
        async with httpx.AsyncClient(timeout=60) as c:
            r=await c.post("https://api.flightpowers.com/v1/flights/roundtrip",headers={"x-api-key":self.key},json=payload); r.raise_for_status(); data=r.json()
        rows=data if isinstance(data,list) else data.get("results",data.get("flights",[])); out=[]
        for i,x in enumerate(rows):
            p=x.get("total_price_as_number") or x.get("price_as_number") or x.get("price")
            if p is None: continue
            airlines=[]
            for k in ("departure_flight_airline","return_flight_airline","airline"):
                if x.get(k) and x[k] not in airlines: airlines.append(str(x[k]))
            out.append(ProviderOffer(self.name,str(x.get("id") or i),q.origin,q.destination,q.departure_date,q.return_date,float(p),q.currency,airlines,x.get("total_stops"),(int(x["total_duration_seconds"])//60 if x.get("total_duration_seconds") else None),x.get("buy_link") or x.get("booking_url"),x.get("price_range_in_relation_to_other_periods") or x.get("price_level"),True,x))
        return out
