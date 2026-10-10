import pytest

from bfa.errors import ErrorCode, classify_mcp_text


@pytest.mark.parametrize("texto,esperado", [
    ("Not found: PETR9", ErrorCode.not_found),
    ("Invalid API key. Get one at https://usebolsai.com", ErrorCode.invalid_api_key),
    ("Rate limit exceeded. Upgrade to Pro", ErrorCode.rate_limited),
    ("API error: boom", ErrorCode.upstream_error),
    ("Invalid indicator. Choose from: cdi", ErrorCode.invalid_input),
    ("Invalid metric. Choose from: pl", ErrorCode.invalid_input),
    ("Need at least 2 tickers to compare.", ErrorCode.invalid_input),
    ("Maximum 5 tickers for comparison.", ErrorCode.invalid_input),
    ("Operator 'between' requires value_upper parameter.", ErrorCode.invalid_input),
])
def test_erros(texto, esperado):
    assert classify_mcp_text(texto) == esperado


@pytest.mark.parametrize("texto", [
    "No data found for any of the tickers.",
    "No companies found to scan.",
    "No stocks found with roe > 10 (scanned 50 companies).",
    "PETR4: R$ 38,10",
])
def test_nao_erros(texto):
    assert classify_mcp_text(texto) is None
