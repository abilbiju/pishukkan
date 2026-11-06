from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    app_secret: str = "dev-only-change-me"
    database_url: str = "sqlite:///./pishukkan.db"
    telegram_bot_token: str = ""
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    groq_api_key: str = ""
    groq_model: str = "qwen/qwen3.8-27b"
    llm_provider: str = "auto"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    dashboard_api_token: str = "dev-token-change-me"
    allowed_origins: str = "http://localhost:8000"
    receipt_dir: str = "./private_receipts"
    timezone: str = "Asia/Kolkata"
    port: int = 8000
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
