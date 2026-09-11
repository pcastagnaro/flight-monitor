import os,httpx
from .base import Query,ProviderOffer
class TravelpayoutsProvider:
    name="travelpayouts"
    def __init__(self): self.token=os.getenv("TRAVELPAYOUTS_API_TOKEN","")
    @property
    def enabled(self): return bool(self.token)
    async def search(self,q:Query):
        params={"origin":q.origin,"destination":q.destination,"depart_date":q.departure_date.strftime("%Y-%m"),"return_date":q.return_date.strftime("%Y-%m"),"currency":q.currency.lower(),"token":self.token,"limit":30}
        async with httpx.AsyncClient(timeout=30) as c:
            r=await c.get("https://api.travelpayouts.com/aviasales/v3/prices_for_dates",params=params); r.raise_for_status(); data=r.json()
        out=[]
        for i,x in enumerate(data.get("data",[])):
            if x.get("departure_at","")[:10]!=q.departure_date.isoformat() or x.get("return_at","")[:10]!=q.return_date.isoformat() or x.get("price") is None: continue
            out.append(ProviderOffer(self.name,str(i),q.origin,q.destination,q.departure_date,q.return_date,float(x["price"]),q.currency,[x.get("airline","")],x.get("transfers"),x.get("duration"),x.get("link"),None,False,x))
        return out
