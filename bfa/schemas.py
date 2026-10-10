"""Modelos Pydantic: envelope único de resposta e requests."""
from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

from bfa.errors import ErrorCode


class ScreenMetric(str, Enum):
    pl = "pl"
    pvp = "pvp"
    ev_ebitda = "ev_ebitda"
    roe = "roe"
    roa = "roa"
    roic = "roic"
    net_margin = "net_margin"
    gross_margin = "gross_margin"
    ebitda_margin = "ebitda_margin"
    dividend_yield = "dividend_yield"
    debt_equity = "debt_equity"


class ErrorInfo(BaseModel):
    code: ErrorCode
    message: str


class ToolResult(BaseModel):
    ok: bool
    tool: str
    data: str | None = None
    error: ErrorInfo | None = None
    cached: bool = False
    latency_ms: int = 0
    fetched_at: datetime


class SnapshotResult(BaseModel):
    ticker: str
    asset_type: Literal["stock", "fii"]
    sections: dict[str, ToolResult]


class ScreenRequest(BaseModel):
    metric: ScreenMetric
    operator: Literal["gt", "lt", "between"]
    value: float
    value_upper: float | None = None
    sector: str | None = None
    limit: int = Field(20, ge=1, le=50)
