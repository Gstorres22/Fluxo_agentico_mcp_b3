"""Configuração do BFA, lida de variáveis de ambiente / arquivo .env."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Chave do Bolsai: validada só ao subir a sessão MCP (não no import)
    BOLSAI_API_KEY: str | None = None
    MCP_COMMAND: str = "uvx"
    # mcp<2: o bolsai-mcp 0.1.1 importa FastMCP, que não existe no mcp 2.x
    MCP_ARGS: list[str] = ["--with", "mcp<2", "bolsai-mcp==0.1.1"]

    # Se definido, as rotas /v1 exigem o header X-BFA-Key
    BFA_API_KEY: str | None = None

    MCP_MAX_CONCURRENCY: int = 4
    MCP_CALL_TIMEOUT_S: float = 30
    MCP_READY_TIMEOUT_S: float = 10

    # TTLs do cache (segundos)
    TTL_QUOTE: int = 60
    TTL_HISTORY: int = 15 * 60
    TTL_MACRO: int = 60 * 60
    TTL_SCREEN: int = 60 * 60
    TTL_FUNDAMENTALS: int = 6 * 60 * 60
    TTL_COMPANIES: int = 24 * 60 * 60


@lru_cache
def get_settings() -> Settings:
    return Settings()
