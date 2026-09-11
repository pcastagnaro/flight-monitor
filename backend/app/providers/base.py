from dataclasses import dataclass,field
from datetime import date
from typing import Protocol
@dataclass
class Query:
    origin:str; destination:str; departure_date:date; return_date:date; adults:int=1; cabin:str="economy"; max_stops:int|None=1; currency:str="EUR"
@dataclass
class ProviderOffer:
    provider:str; provider_offer_id:str|None; origin:str; destination:str; departure_date:date; return_date:date; price:float; currency:str; airlines:list[str]=field(default_factory=list); stops:int|None=None; duration_minutes:int|None=None; booking_url:str|None=None; price_level:str|None=None; live:bool=True; raw:dict=field(default_factory=dict)
class FlightProvider(Protocol):
    name:str
    @property
    def enabled(self)->bool: ...
    async def search(self,q:Query)->list[ProviderOffer]: ...
