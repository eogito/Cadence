from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import SecretStr

class Settings(BaseSettings):
    app_name: str = "AI Task Scheduler"
    environment: str = "development"
    database_url: str
    secret_key: SecretStr
    openai_api_key: SecretStr = SecretStr("")
    groq_api_key: SecretStr = SecretStr("")
    ms_client_id: str = ""
    ms_client_secret: SecretStr = SecretStr("")
    ms_authority: str = "https://login.microsoftonline.com/common"
    ms_redirect_uri: str = "http://localhost:8000/auth/callback"
    session_secret: SecretStr = SecretStr("dev-insecure-session-secret-change-me")
    token_encryption_key: SecretStr = SecretStr("WAApm14ZalIw7D8_oYAH5nw1NW0cOqUCBv4qXyV8I5M=")  # dev-only; override in prod

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()