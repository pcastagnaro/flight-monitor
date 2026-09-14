from app.logging_config import configure_logging
configure_logging()
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import router
app=FastAPI(title="Flight Monitor Multi-Provider",version="2.0.0")
app.add_middleware(CORSMiddleware,allow_origins=[x.strip() for x in os.getenv("CORS_ORIGINS","http://localhost:3000").split(",") if x.strip()],allow_credentials=True,allow_methods=["*"],allow_headers=["*"])
app.include_router(router)
