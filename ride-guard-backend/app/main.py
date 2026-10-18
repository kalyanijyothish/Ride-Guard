import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .database import Base, SessionLocal, engine
from .models import User
from .routers import admin, auth, rides, traffic, ws
from .security import hash_password
from .services import fraud, stream
from .ws_manager import manager

logging.basicConfig(level=logging.INFO)


def bootstrap_admin() -> None:
    if not (settings.ADMIN_EMAIL and settings.ADMIN_PASSWORD):
        return
    with SessionLocal() as db:
        if not db.query(User).filter(User.email == settings.ADMIN_EMAIL.lower()).first():
            db.add(User(email=settings.ADMIN_EMAIL.lower(), name="Administrator", role="admin",
                        password_hash=hash_password(settings.ADMIN_PASSWORD)))
            db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    bootstrap_admin()
    manager.loop = asyncio.get_running_loop()
    fraud.load_or_train()
    if settings.STREAM_MODE == "queue":
        stream.start_worker()
    yield


app = FastAPI(title="Ride Fraud & Traffic Intelligence API", version="1.0.0", lifespan=lifespan)
origins = [o.strip() for o in settings.CORS_ORIGINS.split(",")]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"],
                   allow_credentials=origins != ["*"])

for r in (auth.router, rides.router, traffic.router, traffic.geo, admin.router, ws.router):
    app.include_router(r)


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok"}
