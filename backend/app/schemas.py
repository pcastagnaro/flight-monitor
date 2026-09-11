from datetime import date
from pydantic import BaseModel,Field
class SearchCreate(BaseModel):
    name:str="BCN ↔ Buenos Aires"; origin:str="BCN"; destinations:list[str]=["EZE","AEP"]; departure_from:date; departure_to:date; return_from:date; return_to:date; adults:int=Field(1,ge=1,le=9); cabin:str="economy"; max_stops:int|None=Field(1,ge=0,le=3); target_price:float|None=None; ideal_price:float|None=None; max_price:float|None=None
class SearchOut(SearchCreate):
    id:int; active:bool
    model_config={"from_attributes":True}
