import os
import getpass
from typing import List
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Default to current user on localhost, which is the most common macOS/Homebrew setup.
    database_url: str = f"postgresql://{getpass.getuser()}@localhost:5432/veritas_ai"

    # Deployment environment — controls dev-mode safety bypasses.
    # Allowed values: local | development | staging | production
    # Set ENV=local or ENV=development in .env to enable non-production relaxations.
    env: str = "production"

    # CORS — override in production with a comma-separated list via CORS_ORIGINS env var
    cors_origins: List[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    # Ticket 2.1 — File storage
    storage_path: str = "/app/storage/documents"
    max_file_size_bytes: int = 52_428_800  # 50 MB

    # Ticket 2.4 — Registry freshness gate
    registry_staleness_hours: int = 24

    # EPIC 3 — Draft Generation
    llm_model_name: str = "claude-opus-4-6"
    max_draft_length: int = 50_000  # characters; drafts exceeding this are truncated

    # EPIC 4 — QA + Iteration
    qa_passing_threshold: float = 9.0           # composite score required to PASS
    max_qa_iterations: int = 3                  # default; can be overridden per request
    qa_llm_model: str = "claude-sonnet-4-6"

    # EPIC 6 — Governance Gate
    governance_score_threshold: float = 9.0     # minimum score for governance PASSED

    # EPIC 7 — Review Notifications
    # Set to a webhook endpoint URL to receive POST notifications on approve/reject.
    # Leave empty (default) to disable notifications.
    notification_webhook_url: str = ""

    model_config = {"env_file": ".env"}


settings = Settings()
