"""Configuration from environment variables. Secrets never live in code."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

try:  # optional: load .env when python-dotenv is installed
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:  # pragma: no cover
    pass


class ConfigError(RuntimeError):
    pass


def _get(name: str, default: str | None = None) -> str | None:
    """Read an env var; empty or whitespace-only values count as unset."""
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return value.strip()


def _decimal_env(name: str, default: str) -> Decimal:
    raw = _get(name, default)
    try:
        return Decimal(raw)
    except InvalidOperation as exc:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from exc


@dataclass
class Settings:
    # AMD Developer Cloud: your own vLLM endpoint (used for the health check and benchmark;
    # the Evolus agent calls it directly once you connect it in the workspace).
    vllm_base_url: str | None = field(default_factory=lambda: _get("VLLM_BASE_URL"))
    vllm_api_key: str | None = field(default_factory=lambda: _get("VLLM_API_KEY"))
    vllm_model: str = field(default_factory=lambda: _get("VLLM_MODEL", "ledgerpilot-model"))

    # Evolus event workspace
    evolus_api_base: str = field(default_factory=lambda: _get("EVOLUS_API_BASE", "https://api.evolus.ai/api/v1"))
    evolus_chat_base: str = field(default_factory=lambda: _get("EVOLUS_CHAT_BASE", "https://api.evolus.ai/v1"))
    evolus_api_key: str | None = field(default_factory=lambda: _get("EVOLUS_API_KEY"))
    evolus_app_id: str | None = field(default_factory=lambda: _get("EVOLUS_APP_ID"))
    evolus_agent_id: str | None = field(default_factory=lambda: _get("EVOLUS_AGENT_ID"))
    evolus_extractor_agent_id: str | None = field(default_factory=lambda: _get("EVOLUS_EXTRACTOR_AGENT_ID") or _get("EVOLUS_AGENT_ID"))
    extractor_invoice_id: str | None = field(default_factory=lambda: _get("EVOLUS_EXTRACTOR_INVOICE_ID"))
    extractor_po_id: str | None = field(default_factory=lambda: _get("EVOLUS_EXTRACTOR_PO_ID"))
    extractor_grn_id: str | None = field(default_factory=lambda: _get("EVOLUS_EXTRACTOR_GRN_ID"))
    workflow_id: str | None = field(default_factory=lambda: _get("EVOLUS_WORKFLOW_ID"))
    library_id: str | None = field(default_factory=lambda: _get("EVOLUS_LIBRARY_ID"))

    # Business rules
    price_tolerance: Decimal = field(default_factory=lambda: _decimal_env("PRICE_TOLERANCE", "0.00"))
    vendor_master_path: Path = field(default_factory=lambda: Path(_get("VENDOR_MASTER", str(ROOT / "data" / "vendor_master.csv"))))
    history_path: Path = field(default_factory=lambda: Path(_get("PAYMENT_HISTORY", str(ROOT / "data" / "history.json"))))
    audit_db: Path = field(default_factory=lambda: Path(_get("AUDIT_DB", str(ROOT / "ledgerpilot_audit.db"))))

    def placeholder_vllm(self) -> bool:
        return bool(self.vllm_base_url and "<" in self.vllm_base_url)

    def missing(self) -> list[str]:
        required = {
            "EVOLUS_API_KEY": self.evolus_api_key, "EVOLUS_APP_ID": self.evolus_app_id,
            "EVOLUS_AGENT_ID": self.evolus_agent_id,
            "EVOLUS_EXTRACTOR_INVOICE_ID": self.extractor_invoice_id,
            "EVOLUS_EXTRACTOR_PO_ID": self.extractor_po_id, "EVOLUS_EXTRACTOR_GRN_ID": self.extractor_grn_id,
        }
        return [k for k, v in required.items() if not v]

    def require(self) -> None:
        if gaps := self.missing():
            raise ConfigError("Missing environment variables: " + ", ".join(gaps) + ". Copy .env.example to .env and fill them in.")


def load_settings() -> Settings:
    return Settings()
