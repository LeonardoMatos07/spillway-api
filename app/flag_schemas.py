"""Tariff flag (bandeira) forecast: rule, history, forecast runs and scoreboard."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

FlagName = Literal["Verde", "Amarela", "Vermelha P1", "Vermelha P2"]


class FlagAttribution(BaseModel):
    """Where the numbers come from. The CCEE bulletins are never hosted, only numeric facts."""

    text: str
    sources: list[str]
    legal_note: str


class FlagRuleVersion(BaseModel):
    name: str
    lim_green: float
    lim_yellow: float
    lim_red1: float
    gfom: bool
    effective_from: date | None
    status: str


class FlagGfomStep(BaseModel):
    up_to_mwm: float
    flag: FlagName


class FlagGfomTable(BaseModel):
    original: FlagName
    steps: list[FlagGfomStep]


class FlagRuleResponse(BaseModel):
    """Everything the browser simulator needs: constants, formulas and the latest month."""

    formula: str
    versions: list[FlagRuleVersion]
    gfom: list[FlagGfomTable]
    latest_month: date | None
    latest_rule_version: str | None
    pld_min_brl_per_mwh: float | None
    pld_max_brl_per_mwh: float | None
    gsf: float | None
    pld_trigger_brl_per_mwh: float | None
    flag: str | None
    green_upper_brl_per_mwh: float | None
    yellow_upper_brl_per_mwh: float | None
    red1_upper_brl_per_mwh: float | None
    attribution: FlagAttribution


class FlagMonth(BaseModel):
    month: date
    rule_version: str
    pld_min_brl_per_mwh: float
    pld_max_brl_per_mwh: float
    gh_mwmed: float
    gf_mwmed: float
    gsf: float
    pld_trigger_brl_per_mwh: float
    gfom_mwmed: float
    green_upper_brl_per_mwh: float
    yellow_upper_brl_per_mwh: float
    red1_upper_brl_per_mwh: float
    flag: str
    bulletin_number: int | None
    bulletin_url: str | None
    bulletin_published_on: date | None
    revised_on: date | None


class FlagMonthsResponse(BaseModel):
    items: list[FlagMonth]
    attribution: FlagAttribution


class FlagProbability(BaseModel):
    flag: FlagName
    prob: float
    band_lower_brl_per_mwh: float
    band_upper_brl_per_mwh: float


class FlagForecastRunOut(BaseModel):
    lead_days: int
    generated_at: datetime
    data_through: date
    model_version: str
    rule_version: str
    trigger_p10_brl_per_mwh: float | None
    trigger_p50_brl_per_mwh: float | None
    trigger_p90_brl_per_mwh: float | None
    probabilities: list[FlagProbability]


class FlagForecastResponse(BaseModel):
    """`published` is false until at least one lead passed the publication criterion."""

    published: bool
    target_month: date | None
    official_flag: str | None
    latest_official_month: date | None
    latest_official_flag: str | None
    runs: list[FlagForecastRunOut]
    notice: str
    disclaimer: str
    attribution: FlagAttribution


class FlagScoreItem(BaseModel):
    target_month: date
    lead_days: int
    generated_at: datetime
    actual_flag: FlagName
    prob_actual: float
    brier: float
    top_hit: bool


class FlagScoreSummary(BaseModel):
    lead_days: int
    n: int
    mean_brier: float
    hit_rate: float


class FlagScoreboardResponse(BaseModel):
    items: list[FlagScoreItem]
    summary: list[FlagScoreSummary]
    notice: str
