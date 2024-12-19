from pydantic import UUID4
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv

load_dotenv(".env")

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="allow")
    askui_agent_id: UUID4
    askui_agent_execution_id: UUID4
    askui_workspace_id: UUID4
    askui_token: str
    askui_workspaces_endpoint: str


settings = Settings() # type: ignore
