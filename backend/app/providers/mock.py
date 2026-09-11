import random,hashlib
from .base import Query,ProviderOffer
class MockProvider:
    name="mock"
    @property
    def enabled(self): return True
    async def search(self,q:Query):
        seed=int(hashlib.sha256(f"{q.origin}{q.destination}{q.departure_date}{q.return_date}".encode()).hexdigest()[:8],16); rng=random.Random(seed); price=690+rng.randint(0,260)
        return [ProviderOffer(self.name,f"mock-{seed}",q.origin,q.destination,q.departure_date,q.return_date,float(price),q.currency,["Demo Air"],rng.choice([0,1]),rng.randint(780,1100),None,"low" if price<760 else "typical" if price<900 else "high",False,{"mock":True})]
