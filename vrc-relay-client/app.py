import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from api import dashboard, logs, settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

app = FastAPI(title="VRC配信中継システム Windowsクライアント")

app.include_router(dashboard.router)
app.include_router(settings.router)
app.include_router(logs.router)

app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
