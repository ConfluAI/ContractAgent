import asyncio
import platform

if platform.system() == "Windows":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from server.config import settings
from server.database import init_db, engine
from server.redis_client import close_redis
from graph.workflow import init_checkpointer, close_checkpointer
from config.models import warmup_all
from server.services.checkpoint_cleanup import cleanup_loop


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    try:
        await init_checkpointer(settings.POSTGRES_URL)
    except Exception:
        import logging
        import traceback
        logging.getLogger(__name__).warning(
            "PostgreSQL 不可用，使用内存 checkpointer（重启后状态丢失）\n%s",
            traceback.format_exc(),
        )
    # 预热所有硅基流动 HTTP 连接池（rerank + embedding + LLM），消除首次请求冷启动
    await asyncio.to_thread(warmup_all)
    # 后台定时清理过期 checkpoint（7 天 TTL）
    _cleanup_task = asyncio.create_task(cleanup_loop())
    yield
    _cleanup_task.cancel()
    await engine.dispose()
    await close_redis()
    await close_checkpointer()


app = FastAPI(title="ContractAgent - 合同审查智能体", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from server.routers import auth, users, review, history, conversation  # noqa: E402

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(review.router)
app.include_router(history.router)
app.include_router(conversation.router)


@app.get("/")
async def root():
    return {"message": "ContractAgent API is running"}
