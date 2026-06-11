"""ContractAgent 后端启动脚本 — 确保 Windows 事件循环兼容 psycopg。"""
import asyncio
import platform
import uvicorn

if platform.system() == "Windows":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

if __name__ == "__main__":
    uvicorn.run("server.main:app", host="0.0.0.0", port=8000, reload=True)
