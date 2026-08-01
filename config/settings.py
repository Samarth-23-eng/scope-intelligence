from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    openrouter_api_key: str | None = Field(default=None, repr=False)
    newsapi_key: str | None = Field(default=None, repr=False)
    proxycurl_api_key: str | None = Field(default=None, repr=False)
    postgres_url: str = "postgresql://osint:osint@localhost:5432/osintdb"
    qdrant_url: str = "http://localhost:6333"
    evidence_embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    evidence_embedding_cache: str = ".cache/fastembed"
    evidence_chunk_chars: int = 1600
    evidence_chunk_overlap_chars: int = 200
    evidence_index_batch_size: int = 8
    evidence_retrieval_limit: int = 30
    redis_url: str = "redis://localhost:6379/0"
    # Shared model gateway used by every AI agent. OpenAI-compatible endpoints
    # cover OpenAI, OpenRouter, Ollama, LM Studio, vLLM, LiteLLM, and similar
    # servers. Anthropic and Google are supported through native adapters.
    llm_provider: str = "openai_compatible"
    llm_base_url: str | None = None
    llm_api_key: str | None = Field(default=None, repr=False)
    llm_auth_mode: str = "api_key"
    llm_model: str = "your-model-id"
    llm_request_timeout_seconds: float = 60.0
    llm_master_key: str | None = Field(default=None, repr=False)
    llm_master_key_file: str = ".secrets/llm.key"
    running_in_docker: bool = False
    # Backwards-compatible aliases for installations created before the shared
    # provider gateway. New deployments should use LLM_BASE_URL/LLM_API_KEY.
    nine_router_url: str = "http://localhost:20128/v1"
    nine_router_api_key: str | None = Field(default=None, repr=False)
    analysis_rate_limit_seconds: float = 15.0
    analysis_structured_repair_attempts: int = 1
    analysis_repair_output_chars: int = 12000
    analysis_evidence_pack_max_hits: int = 36
    analysis_evidence_pack_max_chars: int = 50000
    analysis_evidence_pack_per_query: int = 12
    analysis_evidence_pack_max_per_document: int = 3
    analysis_evidence_pack_max_per_domain: int = 8
    cors_origins: str = "http://localhost:3000"
    crawler_max_pages: int = 80
    crawler_max_depth: int = 3
    crawler_concurrency: int = 5
    crawler_max_browser_fallbacks: int = 12
    crawler_request_timeout_seconds: float = 20.0
    crawler_retry_attempts: int = 2
    crawler_respect_robots: bool = True
    crawler_min_content_chars: int = 250
    crawler_max_document_bytes: int = 10000000
    crawler_max_pdf_pages: int = 80
    crawler_max_sitemaps: int = 8
    crawler_max_sitemap_urls: int = 500
    crawler_resume_campaigns: bool = True
    crawler_max_external_profiles: int = 80
    crawler_access_recovery_available: bool = True
    crawler_access_recovery_max_attempts: int = 6
    crawler_access_recovery_impersonate: str = "chrome"
    monitoring_scheduler_enabled: bool = True
    monitoring_scheduler_poll_seconds: int = 30
    enable_job_scraper: bool = True
    enable_linkedin_scraper: bool = False
    job_sources: str = "indeed,google"
    job_results_wanted: int = 30
    job_search_location: str = ""
    job_hours_old: int = 720
    enable_external_sources: bool = True
    youtube_api_key: str | None = Field(default=None, repr=False)
    youtube_max_videos: int = 12
    youtube_comments_per_video: int = 0
    enable_youtube_transcripts: bool = True
    youtube_transcript_languages: str = "en,hi"
    github_token: str | None = Field(default=None, repr=False)
    github_max_repositories: int = 20
    github_releases_per_repository: int = 3
    enable_social_collection: bool = True
    social_max_items_per_run: int = 50
    social_max_comments_per_item: int = 200
    social_max_reply_depth: int = 1
    social_request_delay_seconds: float = 0.25
    social_run_timeout_seconds: float = 900.0
    social_youtube_retention_days: int = 30
    enable_deep_research: bool = False
    tor_socks_proxy_url: str = "socks5h://tor:9050"
    deep_research_max_results: int = 30
    deep_research_max_pages: int = 12
    deep_research_request_delay_seconds: float = 1.0
    deep_research_timeout_seconds: float = 600.0
    deep_research_max_content_bytes: int = 1000000

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def job_source_list(self) -> list[str]:
        sources = [source.strip().lower() for source in self.job_sources.split(",")]
        return [source for source in sources if source]

    @property
    def youtube_transcript_language_list(self) -> list[str]:
        languages = [
            language.strip().lower()
            for language in self.youtube_transcript_languages.split(",")
        ]
        return [language for language in languages if language]


settings = Settings()
