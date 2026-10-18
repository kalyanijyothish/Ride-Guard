from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = "sqlite:///./dev.db"
    JWT_SECRET: str = "change-me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_MINUTES: int = 60 * 24
    GOOGLE_CLIENT_ID: str = ""

    ADMIN_EMAIL: str = ""
    ADMIN_PASSWORD: str = ""

    TOMTOM_API_KEY: str = ""
    OSRM_URL: str = "https://router.project-osrm.org"
    USER_AGENT: str = "RideGuard/1.0 (contact: you@example.com)"

    CORS_ORIGINS: str = "*"
    STREAM_MODE: str = "queue"  # queue | inline
    FRAUD_ALERT_THRESHOLD: float = 0.6
    MODEL_DIR: str = "models"

    BASE_FARE: float = 40.0
    PER_KM: float = 12.0
    PER_MIN: float = 1.5


settings = Settings()
