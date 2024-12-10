from pydantic import UUID4, BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AzureSettings(BaseModel):
    openai_api_key: str
    openai_api_version: str = Field("2023-03-15-preview")
    openai_endpoint: str
    openai_model: str = Field("gpt-4o")
    openai_deployment: str = Field("gpt-4o")


class ExecutionSettings(BaseModel):
    agent_id: UUID4
    agent_execution_id: UUID4


class HubSettings(BaseModel):
    workspace_id: str
    access_token: str
    host: str = Field("http://localhost:8000")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_nested_delimiter="__")
    azure: AzureSettings = Field(default_factory=AzureSettings)  # type: ignore
    execution: ExecutionSettings = Field(default_factory=ExecutionSettings)  # type: ignore
    hub: HubSettings = Field(default_factory=HubSettings)  # type: ignore


settings = Settings()
