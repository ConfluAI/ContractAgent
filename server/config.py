from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "mysql+aiomysql://root:123456@localhost:3306/contract_agent"
    REDIS_URL: str = "redis://localhost:6379/0"
    POSTGRES_URL: str = "postgresql://jjf:Jiangjf1314525.@localhost:5432/contract_checkpoint"
    CHECKPOINT_RETENTION_DAYS: int = 7
    JWT_SECRET_KEY: str = "contract-agent-jwt-secret-key-2024-very-long-and-secure-string"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 1440
    UPLOAD_DIR: str = "uploads"
    CORS_ORIGINS: list[str] = ["http://localhost:5173"]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()
