import unittest
from datetime import date
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.db import Base
from app.models import Search, Offer, PriceSnapshot
from app.api.routes import results

class SourceTests(unittest.TestCase):
    def test_demo_cannot_hide_real_results(self):
        engine=create_engine('sqlite://')
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            s=Search(name='test',origin='BCN',destinations=['EZE'],departure_from=date(2026,11,25),departure_to=date(2026,11,25),return_from=date(2027,1,2),return_to=date(2027,1,2))
            db.add(s);db.flush()
            for i in range(102):
                demo=i<101
                o=Offer(search_id=s.id,fingerprint=str(i),origin='BCN',destination='EZE',departure_date=s.departure_from,return_date=s.return_from,airlines=['Demo Air' if demo else 'Iberia'],best_price=700 if demo else 1000)
                db.add(o);db.flush()
                db.add(PriceSnapshot(offer_id=o.id,provider='mock' if demo else 'datacrawler',price=o.best_price,currency='EUR',raw={}))
            db.commit()
            real=results(s.id,'real',db)
            self.assertEqual(len(real),1)
            self.assertEqual(real[0]['airlines'],['Iberia'])
            demos=results(s.id,'demo',db)
            self.assertEqual(len(demos),100)
            self.assertTrue(all(x['source']=='demo' and x['recommendation'] is None for x in demos))
