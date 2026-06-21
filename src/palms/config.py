from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    oura_client_id: str = ""
    oura_client_secret: str = ""

    withings_client_id: str = ""
    withings_client_secret: str = ""

    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    report_recipient: str = ""

    db_path: str = "data/db/health.db"
    raw_data_path: str = "data/raw"
    default_lookback_days: int = 7


settings = Settings()
