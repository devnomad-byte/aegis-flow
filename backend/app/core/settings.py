from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DB_", extra="ignore")

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


class RedisSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="REDIS_", extra="ignore")

    host: str = "localhost"
    port: int = 6379
    password: SecretStr = Field(default=SecretStr("change-me"), repr=False)
    database: int = 0


class S3Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="S3_", extra="ignore")

    enabled: bool = True
    endpoint: str = "http://localhost:9000"
    region: str = "us-east-1"
    bucket: str = "aegis-flow"
    access_key: SecretStr = Field(default=SecretStr("change-me"), repr=False)
    secret_key: SecretStr = Field(default=SecretStr("change-me"), repr=False)


class MilvusSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MILVUS_", extra="ignore")

    uri: str = "http://localhost:19530"
    username: str = "root"
    password: SecretStr = Field(default=SecretStr("change-me"), repr=False)


class SecuritySettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SECURITY_", extra="ignore")

    access_token_expire_minutes: int = 60


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    app_name: str = "AegisFlow API"
    app_version: str = "0.1.0"
    service_name: str = "aegis-flow-api"
    environment: str = "local"
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    s3: S3Settings = Field(default_factory=S3Settings)
    milvus: MilvusSettings = Field(default_factory=MilvusSettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
