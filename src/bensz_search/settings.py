"""Public site metadata, independent of deployment and search configuration."""

from urllib.parse import urlsplit

from pydantic import Field, field_validator

from .models import StrictModel

DEFAULT_SITE = {
    "site_name": "bensz-search",
    "site_subtitle": "统一搜索，智能路由",
    "default_language": "zh-CN",
    "doc_url": "",
    "support_url": "",
}


class SettingsInput(StrictModel):
    expected_revision: int = Field(ge=0, strict=True)
    site_name: str = Field(min_length=1, max_length=60)
    site_subtitle: str = Field(max_length=160)
    default_language: str = Field(pattern=r"^(zh-CN|en)$")
    doc_url: str = Field(max_length=2048)
    support_url: str = Field(max_length=2048)

    @field_validator("site_name", "site_subtitle", "doc_url", "support_url", mode="before")
    @classmethod
    def trim(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("doc_url", "support_url")
    @classmethod
    def public_url(cls, value):
        if not value:
            return value
        url = urlsplit(value)
        try:
            _ = url.port
        except ValueError as error:
            raise ValueError("Invalid link port") from error
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username
            or url.password
            or any(char.isspace() or ord(char) < 32 for char in value)
            or "\\" in value
        ):
            raise ValueError("Use an HTTP(S) link without credentials")
        return value
