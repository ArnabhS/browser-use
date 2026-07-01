from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openrouter_api_key: str = ""
    agent_model: str = "anthropic/claude-sonnet-4.6"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    max_steps: int = 100
    llm_temperature: float = 0.2
    llm_max_retries: int = 3
    browser_backend: str = "fake"  # "fake" | "local_cdp"
    use_vision: bool = True
    # The page the browser opens on when a session starts (a home page). Google by default so the
    # live view shows something familiar the instant a run begins instead of a blank tab.
    start_url: str = "https://www.google.com"
    # Locale / timezone / geolocation the launched browser presents (India by default). Shapes
    # navigator.language, the Intl timezone, and the JS Geolocation API. NOTE: this does NOT change
    # the server's outbound IP, so IP-based geolocation still reflects the host — use a proxy for
    # true regional IP. Set browser_geolocation to "" to disable the geolocation override.
    browser_locale: str = "en-IN"
    browser_timezone: str = "Asia/Kolkata"
    browser_geolocation: str = "19.0760,72.8777"  # "lat,long" (Mumbai); empty to disable
    runs_dir: str = "runs"
    cdp_headless: bool = False
    # When set (e.g. "http://localhost:9222"), attach to the user's running Chrome over CDP
    # instead of launching a fresh Chromium. Empty = launch a throwaway browser.
    cdp_connect_url: str = ""
    # Diagnostics: when on, log a per-stage funnel trace + a raw-DOM probe each observe so you
    # can see exactly where an element you can SEE but can't click gets dropped. `funnel_focus`
    # is the text to track (e.g. "add to cart"). Off by default; enable via env for a debug run.
    funnel_debug: bool = False
    funnel_focus: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
