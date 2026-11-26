import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from wotapp.config import get_settings
from wotapp.database import init_db
from wotapp.jobs import start_scheduler, stop_scheduler
from wotapp.routers import UTF8JSONResponse, router

logger = logging.getLogger("wotapp")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    init_db()
    if get_settings().scheduler_enabled:
        start_scheduler()
    yield
    stop_scheduler()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="wot-data-analysis", lifespan=lifespan, default_response_class=UTF8JSONResponse)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)
    return app


app = create_app()
