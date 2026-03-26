from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    ANTHROPIC_API_KEY: str = ""
    SUPABASE_URL: str = ""
    SUPABASE_SERVICE_KEY: str = ""
    BRAVE_SEARCH_API_KEY: str = ""
    GMAIL_CREDENTIALS_JSON: str = ""
    NOTION_API_KEY: str = ""
    FACEBOOK_APP_ID: str = ""
    FACEBOOK_APP_SECRET: str = ""
    ENCRYPTION_KEY: str = ""  # Fernet key for token encryption
    FRONTEND_URL: str = "http://localhost:5173"
    MODEL_NAME: str = "claude-sonnet-4-20250514"
    ENVIRONMENT: str = "development"  # development | production

    class Config:
        env_file = ".env"


settings = Settings()
