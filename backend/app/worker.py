import asyncio
from apscheduler.schedulers.blocking import BlockingScheduler
from sqlalchemy import select
from app.db import SessionLocal
from app.models import Search
from app.services.orchestrator import run_search
def run_active_searches():
    db=SessionLocal()
    try:
        ss=db.scalars(select(Search).where(Search.active.is_(True))).all()
        async def go():
            for s in ss: await run_search(db,s)
        asyncio.run(go())
    finally: db.close()
if __name__=="__main__":
    scheduler=BlockingScheduler(timezone="Europe/Madrid"); scheduler.add_job(run_active_searches,"cron",hour=6,minute=0,max_instances=1,coalesce=True); scheduler.start()
