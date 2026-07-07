from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "worldcup-agent"
    debug: bool = False

    # Paths
    data_dir: Path = Path("data")
    docs_dir: Path = Path("docs/teams")
    db_path: Path = Path("data/worldcup.db")
    tournament_db_path: Path = Path("data/tournament.db")
    tournament_snapshot_dir: Path = Path("data/snapshots")
    skill_path: Path = Path("skills/worldcup-compare/SKILL.md")
    worldcup_json_dir: Path = Path("data")
    chroma_persist_dir: Path = Path("data/chroma")
    chroma_collection: str = "worldcup_teams"
    tournament_year: int = 2026

    # CORS for React dev server
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Backends: mock (tests) | chroma / qwen (production)
    rag_backend: str = "mock"
    llm_backend: str = "mock"

    # DashScope / 百炼通义 (OpenAI-compatible)
    dashscope_api_key: str = ""
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    embedding_model: str = "text-embedding-v4"
    llm_model: str = "qwen-plus"
    llm_max_tokens: int = 1024
    llm_temperature: float = 0.3

    # Timeouts (seconds)
    request_timeout: float = 3.0
    tool_timeout: float = 2.5

    # LLM concurrency limit (protect external API rate limits)
    llm_max_concurrency: int = 10

    # Request backpressure: max concurrent in-flight requests
    queue_maxsize: int = 100
    queue_put_timeout: float = 0.5

    # Mock tool behavior
    mock_stats_delay: float = 0.05
    mock_rag_delay: float = 0.3
    mock_llm_delay: float = 0.8
    mock_failure_rate: float = 0.0

    # Odds (P2): mock | the_odds_api
    odds_backend: str = "mock"
    odds_api_key: str = ""
    odds_api_base_url: str = "https://api.the-odds-api.com/v4"
    odds_sport_key: str = "soccer_fifa_world_cup"
    odds_regions: str = "us"
    odds_markets: str = "h2h"


settings = Settings()
