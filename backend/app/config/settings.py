from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openrouter_api_key: str = ""
    agent_model: str = "anthropic/claude-sonnet-4.6"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    max_steps: int = 25
    llm_temperature: float = 0.2
    llm_max_retries: int = 3
    browser_backend: str = "fake"  # "fake" | "local_cdp"
    use_vision: bool = False
    runs_dir: str = "runs"
    cdp_headless: bool = False
    # When set (e.g. "http://localhost:9222"), attach to the user's running Chrome over CDP
    # instead of launching a fresh Chromium. Empty = launch a throwaway browser.
    cdp_connect_url: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
