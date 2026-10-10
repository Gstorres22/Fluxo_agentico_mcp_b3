"""Classificação dos textos de erro devolvidos pelo servidor bolsai-mcp."""
from enum import Enum


class ErrorCode(str, Enum):
    not_found = "not_found"
    invalid_api_key = "invalid_api_key"
    rate_limited = "rate_limited"
    invalid_input = "invalid_input"
    upstream_error = "upstream_error"
    upstream_unavailable = "upstream_unavailable"
    timeout = "timeout"


# Código de erro -> status HTTP
HTTP_STATUS = {
    ErrorCode.not_found: 404,
    ErrorCode.invalid_api_key: 502,
    ErrorCode.rate_limited: 429,
    ErrorCode.invalid_input: 422,
    ErrorCode.upstream_error: 502,
    ErrorCode.upstream_unavailable: 502,
    ErrorCode.timeout: 504,
}

# Prefixos de mensagens do MCP (a ordem importa)
_PREFIXOS = [
    ("Not found:", ErrorCode.not_found),
    ("Invalid API key", ErrorCode.invalid_api_key),
    ("Rate limit exceeded", ErrorCode.rate_limited),
    ("API error:", ErrorCode.upstream_error),
    ("Invalid ", ErrorCode.invalid_input),
    ("Need at least", ErrorCode.invalid_input),
    ("Maximum ", ErrorCode.invalid_input),
    ("Operator 'between'", ErrorCode.invalid_input),
]


def classify_mcp_text(text: str) -> ErrorCode | None:
    """Devolve o ErrorCode se o texto for um erro; None se for dado válido.

    "No data found", "No companies found" e "No stocks found" NÃO são erros:
    são respostas vazias legítimas.
    """
    t = text.strip()
    for prefixo, codigo in _PREFIXOS:
        if t.startswith(prefixo):
            return codigo
    return None


# Respostas vazias do MCP: são "ok", mas NÃO vão para o cache, porque o bolsai-mcp
# também as devolve quando engole erros (ex.: compare_stocks com chave inválida)
_VAZIOS = ("No data found", "No companies found", "No stocks found", "Nenhum dado retornado")


def is_empty_result(text: str) -> bool:
    return text.strip().startswith(_VAZIOS)
