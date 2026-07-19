from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DASHSCOPE_INTL_BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", protected_namespaces=()
    )

    # model access
    model_mode: Literal["api", "local", "mock"] = "mock"
    model_provider: Literal["openrouter", "dashscope", "custom"] = "openrouter"
    openai_base_url: str = ""
    openai_api_key: str = ""
    model_name_fast: str = "qwen/qwen3-vl-235b-a22b-instruct"
    model_name_thinking: str = "qwen/qwen3-vl-235b-a22b-thinking"
    openrouter_data_collection: Literal["allow", "deny"] = "deny"
    openrouter_zdr: bool = False
    # eval 2026-07-19: routing lottery measurably changes detection recall —
    # prefer the first-party backend, keep fallbacks for resilience
    openrouter_provider_order: str = "alibaba"
    openrouter_allow_fallbacks: bool = True
    model_max_concurrency: int = 3
    model_timeout_s: int = 180
    model_max_calls_per_run: int = 400
    record_fixtures: bool = False

    # local mode
    vllm_base_url: str = "http://vllm:8000/v1"
    vllm_model: str = "Qwen/Qwen3-VL-8B-Instruct"

    # storage / db
    database_url: str = ""
    data_dir: Path = Path("./data")
    max_upload_mb: int = 2048

    # pipeline thresholds
    confidence_review_threshold: float = 0.75
    triage_relevance_threshold: float = 0.35
    keyframe_min_interval_s: float = 5.0
    phash_dedup_distance: int = 6
    iou_merge_threshold: float = 0.5
    move_centroid_threshold: float = 0.15
    face_blur_default: bool = True
    # 3b validates today; 3u blocked by WeasyPrint #2841 (Arabic ToUnicode CMap)
    report_pdf_variant: str = "pdf/a-3b"

    # app
    secret_key: str = "dev-insecure-secret-change-me"
    app_env: Literal["dev", "prod"] = "dev"
    log_level: str = "info"

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite+aiosqlite:///{(self.data_dir / 'app.db').as_posix()}"

    @property
    def resolved_base_url(self) -> str:
        if self.model_mode == "local":
            return self.vllm_base_url
        if self.openai_base_url:
            return self.openai_base_url
        if self.model_provider == "dashscope":
            return DASHSCOPE_INTL_BASE_URL
        return OPENROUTER_BASE_URL

    @property
    def is_openrouter(self) -> bool:
        return self.model_mode == "api" and self.model_provider == "openrouter"

    # data layout
    @property
    def originals_dir(self) -> Path:
        return self.data_dir / "originals"

    @property
    def derived_dir(self) -> Path:
        return self.data_dir / "derived"

    @property
    def reports_dir(self) -> Path:
        return self.data_dir / "reports"

    @property
    def tmp_dir(self) -> Path:
        return self.data_dir / "tmp"

    @property
    def fixtures_dir(self) -> Path:
        return Path(__file__).resolve().parent / "fixtures"

    @property
    def prompts_dir(self) -> Path:
        return Path(__file__).resolve().parent / "prompts"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.originals_dir, self.derived_dir,
                  self.reports_dir, self.tmp_dir):
            d.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
