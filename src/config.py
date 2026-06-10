from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import SecretStr

class Settings(BaseSettings):
    app_name: str = "AI Task Scheduler"
    environment: str = "development"
    database_url: str
    google_client_id: str
    google_client_secret: SecretStr
    google_redirect_uri: str
    secret_key: SecretStr
    openai_api_key: SecretStr = SecretStr("")
    groq_api_key: SecretStr = SecretStr("")
    
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()