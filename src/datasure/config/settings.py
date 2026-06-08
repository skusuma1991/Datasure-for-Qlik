from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class QlikSenseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DATASURE_QLIK_")

    # Deployment type
    mode: Literal["enterprise", "cloud", "desktop", "demo"] = "enterprise"

    # Enterprise on Windows
    host: str = "localhost"
    port: int = 443
    virtual_proxy: str = ""          # e.g. "header" or "jwt"
    verify_ssl: bool = True
    ca_cert: Path | None = None      # root.pem from Qlik certificates export
    cert_path: Path | None = None    # client.pem
    key_path: Path | None = None     # client_key.pem

    # Header auth (alternative to certs — needs a virtual proxy configured for header auth)
    user_directory: str = "INTERNAL"
    user_id: str = "sa_repository"

    # Qlik Cloud (SaaS)
    tenant: str = ""                 # e.g. "mycompany.us.qlikcloud.com"
    api_key: str = ""                # from cloud console → API Keys

    timeout: int = 30
    retries: int = 3


class ValidationSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DATASURE_VALIDATION_")

    enabled_modules: list[str] = Field(
        default=[
            "syntax",
            "data_types",
            "field_integrity",
            "data_model_health",
            "duplicates",
            "performance",
            "load_script",
            "resource_optimization",
        ],
        description="Active validation modules",
    )
    fail_fast: bool = False
    max_workers: int = 4
    plugins_dir: Path | None = None


class ReportSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DATASURE_REPORT_")

    output_dir: Path = Path("./reports")
    formats: list[Literal["html", "json", "junit"]] = ["html", "json"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DATASURE_",
        env_nested_delimiter="__",
    )

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    qlik: QlikSenseSettings = Field(default_factory=QlikSenseSettings)
    validation: ValidationSettings = Field(default_factory=ValidationSettings)
    report: ReportSettings = Field(default_factory=ReportSettings)


def load_settings(config_file: Path | None = None) -> Settings:
    if config_file:
        import yaml
        data = yaml.safe_load(Path(config_file).expanduser().read_text())
        qlik       = QlikSenseSettings(**(data.get("qlik") or {}))
        validation = ValidationSettings(**(data.get("validation") or {}))
        report     = ReportSettings(**(data.get("report") or {}))
        return Settings(
            log_level=data.get("log_level", "INFO"),
            qlik=qlik,
            validation=validation,
            report=report,
        )
    return Settings()
