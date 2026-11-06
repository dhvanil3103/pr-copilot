import logging
import uuid
from contextlib import asynccontextmanager

from aiokafka import AIOKafkaProducer
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from api.reviews import router as reviews_router
from api.webhooks import router as webhooks_router
from shared.config import Settings, get_settings
from shared.db import make_engine, make_session_factory
from shared.kafka import ensure_topics, kafka_reachable, make_producer
from shared.logging import configure_logging, request_id

log = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await ensure_topics(settings)
        engine = make_engine(settings.database_url)
        producer: AIOKafkaProducer = make_producer(settings)
        await producer.start()
        app.state.engine = engine
        app.state.session_factory = make_session_factory(engine)
        app.state.producer = producer
        try:
            yield
        finally:
            await producer.stop()
            await engine.dispose()

    app = FastAPI(title="PR Copilot", lifespan=lifespan)
    app.state.settings = settings

    # CORS is only for the local Vite dev server; empty by default so production
    # (same-origin behind the ingress) allows nothing cross-origin.
    if settings.cors_allow_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_allow_origins,
            allow_methods=["GET"],
            allow_headers=["*"],
        )

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        token = request_id.set(rid)
        try:
            response = await call_next(request)
        finally:
            request_id.reset(token)
        response.headers["x-request-id"] = rid
        return response

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz(request: Request):
        checks = {"database": False, "kafka": False}
        try:
            async with request.app.state.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            checks["database"] = True
        except Exception:
            log.exception("database readiness check failed")
        checks["kafka"] = await kafka_reachable(settings)
        ok = all(checks.values())
        return JSONResponse(checks, status_code=200 if ok else 503)

    app.include_router(webhooks_router)
    app.include_router(reviews_router)
    return app
