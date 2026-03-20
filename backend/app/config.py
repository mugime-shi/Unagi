from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Namazu API"
    debug: bool = False
    api_key: str = ""  # X-Namazu-Key header value (empty = auth disabled)

    database_url: str = "postgresql://namazu:namazu@localhost:5432/namazu"

    @property
    def is_local_db(self) -> bool:
        return "localhost" in self.database_url or "db:5432" in self.database_url

    entsoe_api_key: str = ""
    eur_to_sek_rate: float = 11.0  # fallback fixed rate; replace with Riksbank API later

    default_area: str = "SE3"

    # VAPID keys for Web Push notifications (generate with scripts/gen_vapid_keys.py)
    vapid_private_key: str = ""  # base64url-encoded raw 32-byte P-256 private key
    vapid_public_key: str = ""  # base64url-encoded uncompressed EC point (65 bytes)
    vapid_contact: str = "mailto:namazu@example.com"

    # Telegram Bot notifications (single-user; get token from @BotFather, chat_id from /getUpdates)
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""


settings = Settings()
