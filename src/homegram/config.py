"""Runtime configuration, read from environment variables (or a `.env` file)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

IdSet = Annotated[frozenset[int], NoDecode]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    telegram_bot_token: str

    # Access control: an update is accepted if its user OR its chat is listed here.
    allowed_user_ids: IdSet = frozenset()
    allowed_chat_ids: IdSet = frozenset()

    data_dir: Path = Path("/data")
    log_level: str = "INFO"

    shopping_backend: Literal["sqlite", "homeassistant"] = "sqlite"

    # Optional Home Assistant integration.
    ha_url: str | None = None
    ha_token: str | None = None
    ha_shopping_entity: str = "todo.shopping_list"

    @field_validator("allowed_user_ids", "allowed_chat_ids", mode="before")
    @classmethod
    def _parse_id_list(cls, value: Any) -> Any:
        if isinstance(value, str):
            parts = value.replace(";", ",").replace(" ", ",").split(",")
            return frozenset(int(p) for p in parts if p.strip())
        if isinstance(value, int):
            return frozenset({value})
        return value

    @field_validator("ha_url", "ha_token", mode="before")
    @classmethod
    def _empty_to_none(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def _check_homeassistant(self) -> Settings:
        if self.shopping_backend == "homeassistant" and not self.homeassistant_enabled:
            raise ValueError("SHOPPING_BACKEND=homeassistant requires HA_URL and HA_TOKEN")
        return self

    @property
    def homeassistant_enabled(self) -> bool:
        return bool(self.ha_url and self.ha_token)

    @property
    def database_path(self) -> Path:
        return self.data_dir / "homegram.db"
