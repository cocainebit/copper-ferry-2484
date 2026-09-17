from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    dev_mode: bool = False
    dev_token: str = "local-development-only"
    database_url: str = "sqlite:///./.local/desktop.db"
    public_url: str = "http://localhost:3000"
    supabase_url: str = ""
    encryption_key: str = ""
    signing_key: str = ""
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_subscription_price: str = ""
    stripe_topup_price: str = ""
    opensandbox_domain: str = "localhost:8080"
    opensandbox_protocol: str = "http"
    opensandbox_api_key: str = ""
    desktop_image: str = "agent-desktop:local"
    # True only where the runtime sizes home volumes (OpenSandbox Kubernetes). Docker ignores PVC size.
    storage_quota_enforced: bool = False
    anthropic_model: str = "claude-sonnet-4-6"
    max_desktops: int = 4
    paid_saved_computers: int = 2
    paid_running_computers: int = 1
    trial_saved_computers: int = 1
    trial_running_computers: int = 1
    launch_enabled: bool = False
    ops_token: str = ""
    x402_enabled: bool = False
    x402_network: str = "eip155:84532"
    x402_asset: str = ""
    x402_pay_to: str = ""
    x402_rpc_url: str = ""
    x402_facilitator_url: str = ""
    x402_facilitator_token: str = ""
    x402_token_name: str = "USDC"
    x402_token_version: str = "2"
    x402_confirmations: int = 3
    x402_max_timeout_seconds: int = 300
    cubicle_minute_micro_usdc: int = 3334
    platform_service_prices: dict[str, int] = {}
    platform_service_tokens: dict[str, str] = {}
    run_minutes: int = 60
    max_steps: int = 200
    trial_adapter_url: str = ""
    trial_adapter_key: str = ""
    trial_chain: str = ""
    trial_token: str = ""
    trial_recipient: str = ""
    trial_decimals: int = -1
    trial_credits: int = 600
    trial_services: dict[str, int] = {"agent-desktop": 600}
    allowed_origins: list[str] = []


@lru_cache
def settings():
    s = Settings()
    if not s.dev_mode and (
        not all((s.supabase_url, s.encryption_key, s.signing_key)) or s.database_url.startswith("sqlite")
    ):
        raise RuntimeError("Production requires Postgres, Supabase, encryption and signing keys")
    return s
