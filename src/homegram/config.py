"""Runtime configuration, read from environment variables (or a `.env` file)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

IdSet = Annotated[frozenset[int], NoDecode]
StrList = Annotated[tuple[str, ...], NoDecode]  # comma-separated in the environment


ENERGY_SENSOR_SETTINGS = (
    "energy_solar_power",
    "energy_load_power",
    "energy_grid_power",
    "energy_battery_power",
    "energy_battery_soc",
    "energy_solar_today",
    "energy_load_today",
    "energy_import_today",
    "energy_export_today",
    "energy_forecast_today",
    "energy_forecast_tomorrow",
    "energy_peak_tomorrow",
)


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
    # Old HA automation that used to send the tracker notifications (before they moved to
    # Telegram): its muted products are imported once. The bot no longer changes it.
    ha_tracker_automation: str = "tracker_notifica"

    # Robot vacuum (/bind pulizie): notifications when it starts, gets stuck, or a part wears out.
    ha_vacuum: str | None = None
    ha_vacuum_battery: str | None = None  # sensor with the battery level (%)
    ha_vacuum_error: str | None = None  # sensor whose `description` attribute explains errors
    ha_vacuum_parts: StrList = ()  # lifespan sensors (%); empty = every % sensor of the robot
    vacuum_parts_threshold: float = 10

    # Waste collection (/spazzatura): sensors of the waste_collection_schedule integration
    # (empty = found automatically), reminder the evening before and its repetition.
    ha_waste_sensors: StrList = ()
    waste_reminder_time: str = "19:30"
    waste_repeat_time: str = "21:30"  # empty: no repetition

    # Scenes (/scene): scripts or scenes to show. Empty = every scene and every script
    # without input fields.
    ha_scenes: StrList = ()

    # Energy (/energia): sensors, all optional (missing ones are left out).
    energy_solar_power: str | None = None  # kW or W, production now
    energy_load_power: str | None = None  # house consumption now
    energy_grid_power: str | None = None  # > 0 import, < 0 export
    energy_battery_power: str | None = None  # > 0 charging, < 0 discharging
    energy_battery_soc: str | None = None  # %
    energy_solar_today: str | None = None  # kWh
    energy_load_today: str | None = None
    energy_import_today: str | None = None
    energy_export_today: str | None = None
    energy_forecast_today: str | None = None  # kWh (e.g. forecast.solar)
    energy_forecast_tomorrow: str | None = None
    energy_peak_tomorrow: str | None = None  # timestamp of tomorrow's peak
    energy_surplus_kw: float = 1.0  # notify once a day when exporting more than this
    energy_report_time: str = "21:00"  # daily summary + tomorrow's forecast; empty: off

    @field_validator("allowed_user_ids", "allowed_chat_ids", mode="before")
    @classmethod
    def _parse_id_list(cls, value: Any) -> Any:
        if isinstance(value, str):
            parts = value.replace(";", ",").replace(" ", ",").split(",")
            return frozenset(int(p) for p in parts if p.strip())
        if isinstance(value, int):
            return frozenset({value})
        return value

    @field_validator("ha_vacuum_parts", "ha_waste_sensors", "ha_scenes", mode="before")
    @classmethod
    def _parse_str_list(cls, value: Any) -> Any:
        if isinstance(value, str):
            return tuple(p.strip() for p in value.replace(";", ",").split(",") if p.strip())
        return value

    @field_validator(
        "ha_url",
        "ha_token",
        "ha_vacuum",
        "ha_vacuum_battery",
        "ha_vacuum_error",
        *ENERGY_SENSOR_SETTINGS,
        mode="before",
    )
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
    def energy_sensors(self) -> dict[str, str]:
        """Configured energy sensors by setting name (without the `energy_` prefix)."""
        return {
            name.removeprefix("energy_"): value
            for name in ENERGY_SENSOR_SETTINGS
            if (value := getattr(self, name))
        }

    @property
    def database_path(self) -> Path:
        return self.data_dir / "homegram.db"
