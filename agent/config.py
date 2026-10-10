"""Configuração do agente. As chaves NÃO são exigidas no import: são validadas no uso."""
import os

from dotenv import load_dotenv

load_dotenv()  # lê o .env da pasta atual (se existir)


def bfa_url() -> str:
    return os.environ.get("BFA_URL", "http://127.0.0.1:8000")


def bfa_api_key() -> str | None:
    return os.environ.get("BFA_API_KEY") or None


def require_openai_key() -> None:
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY não definida. Copie .env.example para .env e preencha.")
