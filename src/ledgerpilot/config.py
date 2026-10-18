"""Configuration from environment variables. Secrets never live in code."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]

# AMD Token Factory (AMD Radeon Cloud): free, shared, OpenAI-compatible model API.
# Sign in and redeem the team key at TOKEN_FACTORY_SIGN_IN; every teammate must redeem first.
TOKEN_FACTORY_URL = "https://developer.amd.com.cn/radeon/api/v1"
TOKEN_FACTORY_HOST = urlparse(TOKEN_FACTORY_URL).hostname
TOKEN_FACTORY_SIGN_IN = "https://notebooks.amd.com/tokenfactory"
TOKEN_FACTORY_MODEL = "DeepSeek-V4-Flash"  # free, fast, no thinking unless asked, supports tool calls
VLLM_MODEL = "ledgerpilot-model"  # --served-model-name on your own vLLM droplet

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


def _first(*names: str) -> str | None:
    """The first of several env vars that is set (new AMD_* names win over the older VLLM_* ones)."""
    return next((v for v in map(_get, names) if v is not None), None)


def _decimal_env(name: str, default: str) -> Decimal:
    raw = _get(name, default)
    try:
        return Decimal(raw)
    except InvalidOperation as exc:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from exc


@dataclass
class Settings:
    # The AMD model endpoint: AMD Token Factory by default, or your own vLLM server on AMD Developer
    # Cloud. Used here for the health check, speed test and benchmark; the Evolus agent calls the
    # same endpoint once you connect it in the workspace. VLLM_* names still work as fallbacks.
    amd_base_url: str = field(default_factory=lambda: _first("AMD_BASE_URL", "VLLM_BASE_URL") or TOKEN_FACTORY_URL)
    amd_api_key: str | None = field(default_factory=lambda: _first("AMD_API_KEY", "VLLM_API_KEY"))
    amd_model: str | None = field(default_factory=lambda: _first("AMD_MODEL", "VLLM_MODEL"))
    # Optional: none/low/medium/high..., sent as reasoning_effort (thinking tokens count toward max_tokens)
    amd_reasoning_effort: str | None = field(default_factory=lambda: _get("AMD_REASONING_EFFORT"))

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
    max_tax_rate: Decimal = field(default_factory=lambda: _decimal_env("MAX_TAX_RATE", "0.30"))
    vendor_master_path: Path = field(default_factory=lambda: Path(_get("VENDOR_MASTER", str(ROOT / "data" / "vendor_master.csv"))))
    history_path: Path = field(default_factory=lambda: Path(_get("PAYMENT_HISTORY", str(ROOT / "data" / "history.json"))))
    audit_db: Path = field(default_factory=lambda: Path(_get("AUDIT_DB", str(ROOT / "ledgerpilot_audit.db"))))
    # Saved outputs of real live runs, replayed by the app's demo mode
    recordings_dir: Path = field(default_factory=lambda: Path(_get("RECORDINGS_DIR", str(ROOT / "data" / "recordings"))))

    # Public deployment (PUBLIC_SITE=1): every visitor gets a private history, only the sample invoices can be
    # checked live, and live checks are capped so strangers can't use up the team's shared quota.
    public_site: bool = field(default_factory=lambda: (_get("PUBLIC_SITE") or "").lower() in {"1", "true", "yes"})
    live_checks_per_visitor: int = field(default_factory=lambda: int(_get("LIVE_CHECKS_PER_VISITOR", "5")))
    live_checks_per_hour: int = field(default_factory=lambda: int(_get("LIVE_CHECKS_PER_HOUR", "20")))
    chat_messages_per_visitor: int = field(default_factory=lambda: int(_get("CHAT_MESSAGES_PER_VISITOR", "20")))

    # Seconds to wait for one Evolus call / one agent answer before giving the case to a person
    evolus_timeout: Decimal = field(default_factory=lambda: _decimal_env("EVOLUS_TIMEOUT", "90"))
    agent_timeout: Decimal = field(default_factory=lambda: _decimal_env("AGENT_TIMEOUT", "90"))

    def __post_init__(self) -> None:
        if not self.amd_model:
            self.amd_model = TOKEN_FACTORY_MODEL if self.token_factory else VLLM_MODEL

    @property
    def token_factory(self) -> bool:
        return urlparse(self.amd_base_url).hostname == TOKEN_FACTORY_HOST

    @property
    def model_where(self) -> str:
        """Where the model runs, for labels in the app and reports."""
        return "AMD Token Factory" if self.token_factory else "AMD MI300X (vLLM)"

    def placeholder_model(self) -> bool:
        return "<" in self.amd_base_url

    def model_problem(self) -> str | None:
        """Why the AMD endpoint can't be called yet, or None when it is configured."""
        if self.placeholder_model():
            return "AMD_BASE_URL still has a placeholder like <DROPLET_IP>. Set your real address."
        if self.token_factory and not self.amd_api_key:
            return (f"AMD_API_KEY isn't set. Redeem your team's Token Factory key (rc-...) at "
                    f"{TOKEN_FACTORY_SIGN_IN} and add it to .env.")
        return None

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
