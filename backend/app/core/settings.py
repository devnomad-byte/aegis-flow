from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL

LOCAL_ENV_FILES = (".env.local", ".env")


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DB_",
        env_file=LOCAL_ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = "localhost"
    port: int = 5432
    name: str = "aegis_flow"
    username: str = "postgres"
    password: SecretStr = Field(default=SecretStr("change-me"), repr=False)

    @property
    def sqlalchemy_url(self) -> str:
        return URL.create(
            drivername="postgresql+asyncpg",
            username=self.username,
            password=self.password.get_secret_value(),
            host=self.host,
            port=self.port,
            database=self.name,
        ).render_as_string(hide_password=False)

    @property
    def psycopg_url(self) -> str:
        return URL.create(
            drivername="postgresql",
            username=self.username,
            password=self.password.get_secret_value(),
            host=self.host,
            port=self.port,
            database=self.name,
        ).render_as_string(hide_password=False)


class RedisSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="REDIS_",
        env_file=LOCAL_ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = "localhost"
    port: int = 6379
    password: SecretStr = Field(default=SecretStr("change-me"), repr=False)
    database: int = 0


class WorkflowQueueSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="WORKFLOW_QUEUE_",
        env_file=LOCAL_ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    enabled: bool = True
    poll_interval_seconds: float = 0.5
    lease_seconds: int = 60
    max_attempts: int = 3
    retry_backoff_base_seconds: int = 5
    payload_ttl_seconds: int = 86_400
    encryption_secret: SecretStr = Field(
        default=SecretStr("local-dev-workflow-queue-secret"),
        repr=False,
    )
    encryption_key_ref: str = "local-fernet:v1"
    redis_wakeup_enabled: bool = True
    redis_wakeup_channel: str = "aegisflow:workflow-runs:wakeup"
    redis_wakeup_ttl_seconds: int = 60


class ShellImageSupplyChainSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SHELL_IMAGE_SUPPLY_CHAIN_",
        env_file=LOCAL_ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    trivy_enabled: bool = False
    trivy_command: str = "trivy"
    trivy_cache_dir: str = r"D:\agent-platform-cache\trivy"
    cosign_enabled: bool = False
    cosign_command: str = "cosign"
    cosign_certificate_identity: str = ""
    cosign_certificate_oidc_issuer: str = ""
    cosign_key_ref: str = ""
    notation_command: str = "notation"
    notation_work_dir: str = r"D:\agent-platform-cache\notation"
    scan_timeout_seconds: float = 120.0
    blocked_severities: str = "HIGH,CRITICAL"

    @property
    def blocked_severity_set(self) -> frozenset[str]:
        return frozenset(
            severity.strip().upper()
            for severity in self.blocked_severities.split(",")
            if severity.strip()
        )


class S3Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="S3_",
        env_file=LOCAL_ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    enabled: bool = True
    endpoint: str = "http://localhost:9000"
    region: str = "us-east-1"
    bucket: str = "aegis-flow"
    access_key: SecretStr = Field(default=SecretStr("change-me"), repr=False)
    secret_key: SecretStr = Field(default=SecretStr("change-me"), repr=False)


class MilvusSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MILVUS_",
        env_file=LOCAL_ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    uri: str = "http://localhost:19530"
    username: str = "root"
    password: SecretStr = Field(default=SecretStr("change-me"), repr=False)


class SecuritySettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SECURITY_",
        env_file=LOCAL_ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    access_token_expire_minutes: int = 60


class OpenAICompatibleSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="",
        env_file=LOCAL_ENV_FILES,
        env_file_encoding="utf-8",
        populate_by_name=True,
        extra="ignore",
    )

    base_url: str = Field(
        default="https://api.openai.com",
        validation_alias=AliasChoices("OPENAI_COMPATIBLE_BASE_URL", "ANTHROPIC_BASE_URL"),
    )
    auth_token: SecretStr = Field(
        default=SecretStr(""),
        repr=False,
        validation_alias=AliasChoices("OPENAI_COMPATIBLE_AUTH_TOKEN", "ANTHROPIC_AUTH_TOKEN"),
    )
    timeout_seconds: float = Field(
        default=30.0,
        validation_alias=AliasChoices(
            "OPENAI_COMPATIBLE_TIMEOUT_SECONDS",
            "ANTHROPIC_TIMEOUT_SECONDS",
        ),
    )

    @property
    def has_auth_token(self) -> bool:
        return bool(self.auth_token.get_secret_value().strip())

    @property
    def chat_completions_url(self) -> str:
        normalized_base_url = self.base_url.rstrip("/")
        if normalized_base_url.endswith("/v1"):
            return f"{normalized_base_url}/chat/completions"
        return f"{normalized_base_url}/v1/chat/completions"


class ModelGatewaySettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MODEL_",
        env_file=LOCAL_ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    default_provider: str = "openai-compatible"
    default_model: str = "gpt-5.5"
    openai_compatible: OpenAICompatibleSettings = Field(default_factory=OpenAICompatibleSettings)


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="",
        env_file=LOCAL_ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "AegisFlow API"
    app_version: str = "0.1.0"
    service_name: str = "aegis-flow-api"
    environment: str = "local"
    workflow_checkpoint_setup_on_startup: bool = False
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    workflow_queue: WorkflowQueueSettings = Field(default_factory=WorkflowQueueSettings)
    shell_image_supply_chain: ShellImageSupplyChainSettings = Field(
        default_factory=ShellImageSupplyChainSettings
    )
    s3: S3Settings = Field(default_factory=S3Settings)
    milvus: MilvusSettings = Field(default_factory=MilvusSettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    model_gateway: ModelGatewaySettings = Field(default_factory=ModelGatewaySettings)
