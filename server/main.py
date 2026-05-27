from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from server.config import settings
from server.database import init_db, engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield
    await engine.dispose()


app = FastAPI(title="ContractAgent - 合同审查智能体", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from server.routers import auth, users, review, history  # noqa: E402

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(review.router)
app.include_router(history.router)


@app.get("/")
async def root():
    return {"message": "ContractAgent API is running"}
