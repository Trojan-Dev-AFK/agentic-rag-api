# Pydantic BaseSettings (loads .env)
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # Database
    DATABASE_URL_ASYNC: str
    DATABASE_URL_SYNC: str

    # Redis / Celery
    REDIS_URL: str

    # Security
    SECRET_KEY: str
    ALGORITHM: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int

    # Embedding
    EMBEDDING_MODEL: str
    CHUNK_SIZE: int
    CHUNK_OVERLAP: int

    # Encoding
    ENCODING: str

    # Document upload
    UPLOAD_DIR: str

    # This tells Pydantic to look for the .env file in the root directory
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

# We instantiate it once here so the rest of the app can just import 'settings'
settings = Settings()
