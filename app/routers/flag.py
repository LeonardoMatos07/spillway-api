"""Tariff flag forecast: the rule, the monthly history, the forecast runs and the scoreboard.

The forecast is written by the batch job of ``spillway-forecast`` (role ``energia_forecast``) and
only runs with ``status = 'ready'`` are visible. The job writes runs only for leads that passed
the publication criterion, so before that this API answers ``published: false`` and the page
shows the calculator, the history and the scoreboard only. Nothing here is the ANEEL decision.
"""

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.cache import PublicCacheDep
from app.db import SessionDep
from app.flag_schemas import (
    FlagAttribution,
    FlagForecastResponse,
    FlagForecastRunOut,
    FlagGfomStep,
    FlagGfomTable,
    FlagMonth,
    FlagMonthsResponse,
    FlagProbability,
    FlagRuleResponse,
    FlagRuleVersion,
    FlagScoreboardResponse,
    FlagScoreItem,
    FlagScoreSummary,
)
from app.models import (
    FlagForecastProb,
    FlagForecastRun,
    FlagForecastScore,
    FlagRuleMonth,
    TariffFlagMonthly,
)

router = APIRouter(prefix="/v1/flag", tags=["flag"])

STATUS = "adjusted, to be confirmed in Annex I of REH 3.306/2024"
FORMULA = (
    "GSF = round(GH / GF, 2); limit = min(PLDmax, max(PLDmin, Lim / (1 - GSF))) for each of the "
    "three Lim of the rule version (GSF >= 1 puts every limit at PLDmax); the flag is the band "
    "that holds the PLD trigger; GFOM (thermal dispatch outside merit order) can raise it."
)
VERSIONS = [
    FlagRuleVersion(
        name="B",
        lim_green=31.9275,
        lim_yellow=69.059,
        lim_red1=92.4683,
        gfom=False,
        effective_from=None,
        status=STATUS,
    ),
    FlagRuleVersion(
        name="C",
        lim_green=27.4798,
        lim_yellow=68.992,
        lim_red1=95.0522,
        gfom=True,
        effective_from=date(2024, 4, 1),
        status=STATUS,
    ),
]
# InfoBandeira 92 (dec/2025), Table 2; to be confirmed in REN 1.084/2024.
GFOM = [
    (
        "Verde",
        [(6962, "Verde"), (11362, "Amarela"), (14262, "Vermelha P1"), (16562, "Vermelha P2")],
    ),
    ("Amarela", [(9262, "Amarela"), (12162, "Vermelha P1"), (16562, "Vermelha P2")]),
    ("Vermelha P1", [(11462, "Vermelha P1"), (14262, "Vermelha P2")]),
    ("Vermelha P2", [(11762, "Vermelha P2")]),
]
ATTRIBUTION = FlagAttribution(
    text=(
        "Fonte dos números da regra: CCEE, InfoBandeira Tarifária (só fatos numéricos, com número, "
        "data e link do boletim) e ANEEL (cor oficial, dados abertos, ODbL)."
    ),
    sources=["CCEE InfoBandeira Tarifária", "ANEEL dados abertos"],
    legal_note=(
        "Os termos da CCEE limitam a reprodução de conteúdo a fins sem fins lucrativos. "
        "É preciso parecer jurídico antes de qualquer uso comercial."
    ),
)
DISCLAIMER = (
    "Previsão estatística, não é a decisão da ANEEL nem aconselhamento financeiro. A bandeira "
    "oficial é a anunciada pela ANEEL."
)
NOT_PUBLISHED = (
    "Previsão em avaliação: ainda não há prazo que tenha passado no critério de publicação. "
    "Use a calculadora, o histórico e o placar."
)
FLAG_ORDER = ("Verde", "Amarela", "Vermelha P1", "Vermelha P2")


def _f(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


def _month(row: FlagRuleMonth) -> FlagMonth:
    return FlagMonth(
        month=row.month,
        rule_version=row.rule_version,
        pld_min_brl_per_mwh=float(row.pld_min_brl_per_mwh),
        pld_max_brl_per_mwh=float(row.pld_max_brl_per_mwh),
        gh_mwmed=float(row.gh_mwmed),
        gf_mwmed=float(row.gf_mwmed),
        gsf=float(row.gsf),
        pld_trigger_brl_per_mwh=float(row.pld_trigger_brl_per_mwh),
        gfom_mwmed=float(row.gfom_mwmed),
        green_upper_brl_per_mwh=float(row.green_upper_brl_per_mwh),
        yellow_upper_brl_per_mwh=float(row.yellow_upper_brl_per_mwh),
        red1_upper_brl_per_mwh=float(row.red1_upper_brl_per_mwh),
        flag=row.flag,
        bulletin_number=row.bulletin_number,
        bulletin_url=row.bulletin_url,
        bulletin_published_on=row.bulletin_published_on,
        revised_on=row.revised_on,
    )


@router.get("/rule", response_model=FlagRuleResponse)
def flag_rule(session: SessionDep, cache: PublicCacheDep) -> FlagRuleResponse:
    """Constants and formulas of the rule, plus the latest month, for the browser simulator."""

    def load() -> FlagRuleResponse:
        latest = session.scalars(
            select(FlagRuleMonth).order_by(FlagRuleMonth.month.desc()).limit(1)
        ).first()
        month = _month(latest) if latest else None
        return FlagRuleResponse(
            formula=FORMULA,
            versions=VERSIONS,
            gfom=[
                FlagGfomTable(
                    original=original,
                    steps=[FlagGfomStep(up_to_mwm=up, flag=flag) for up, flag in steps],
                )
                for original, steps in GFOM
            ],
            latest_month=month.month if month else None,
            latest_rule_version=month.rule_version if month else None,
            pld_min_brl_per_mwh=month.pld_min_brl_per_mwh if month else None,
            pld_max_brl_per_mwh=month.pld_max_brl_per_mwh if month else None,
            gsf=month.gsf if month else None,
            pld_trigger_brl_per_mwh=month.pld_trigger_brl_per_mwh if month else None,
            flag=month.flag if month else None,
            green_upper_brl_per_mwh=month.green_upper_brl_per_mwh if month else None,
            yellow_upper_brl_per_mwh=month.yellow_upper_brl_per_mwh if month else None,
            red1_upper_brl_per_mwh=month.red1_upper_brl_per_mwh if month else None,
            attribution=ATTRIBUTION,
        )

    return cache.get_or_set(load)


@router.get("/months", response_model=FlagMonthsResponse)
def flag_months(
    session: SessionDep,
    cache: PublicCacheDep,
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
) -> FlagMonthsResponse:
    """Month by month: PLD limits, GH, GF, GSF, PLD trigger, bands and flag (from the bulletins)."""

    def load() -> FlagMonthsResponse:
        stmt = select(FlagRuleMonth).order_by(FlagRuleMonth.month)
        if date_from:
            stmt = stmt.where(FlagRuleMonth.month >= date_from)
        if date_to:
            stmt = stmt.where(FlagRuleMonth.month <= date_to)
        return FlagMonthsResponse(
            items=[_month(row) for row in session.scalars(stmt).all()], attribution=ATTRIBUTION
        )

    return cache.get_or_set(load)


@router.get("/forecast", response_model=FlagForecastResponse)
def flag_forecast(session: SessionDep, cache: PublicCacheDep) -> FlagForecastResponse:
    """Latest ready run of each published lead for the newest target month."""

    def load() -> FlagForecastResponse:
        last_official = session.scalars(
            select(TariffFlagMonthly).order_by(TariffFlagMonthly.month.desc()).limit(1)
        ).first()
        target = session.scalar(
            select(func.max(FlagForecastRun.target_month)).where(FlagForecastRun.status == "ready")
        )
        runs: list[FlagForecastRunOut] = []
        official = None
        if target is not None:
            rows = session.scalars(
                select(FlagForecastRun)
                .where(FlagForecastRun.target_month == target, FlagForecastRun.status == "ready")
                .order_by(FlagForecastRun.lead_days.desc(), FlagForecastRun.generated_at.desc())
            ).all()
            newest: dict[int, FlagForecastRun] = {}
            for row in rows:
                newest.setdefault(row.lead_days, row)
            for lead in sorted(newest, reverse=True):
                run = newest[lead]
                probs = session.scalars(
                    select(FlagForecastProb).where(FlagForecastProb.run_id == run.id)
                ).all()
                runs.append(
                    FlagForecastRunOut(
                        lead_days=run.lead_days,
                        generated_at=run.generated_at,
                        data_through=run.data_through,
                        model_version=run.model_version,
                        rule_version=run.rule_version,
                        trigger_p10_brl_per_mwh=_f(run.trigger_p10_brl_per_mwh),
                        trigger_p50_brl_per_mwh=_f(run.trigger_p50_brl_per_mwh),
                        trigger_p90_brl_per_mwh=_f(run.trigger_p90_brl_per_mwh),
                        probabilities=[
                            FlagProbability(
                                flag=p.flag,
                                prob=float(p.prob),
                                band_lower_brl_per_mwh=float(p.band_lower_brl_per_mwh),
                                band_upper_brl_per_mwh=float(p.band_upper_brl_per_mwh),
                            )
                            for p in sorted(probs, key=lambda p: FLAG_ORDER.index(p.flag))
                        ],
                    )
                )
            official_row = session.get(TariffFlagMonthly, target)
            official = official_row.flag if official_row else None
        return FlagForecastResponse(
            published=bool(runs),
            target_month=target,
            official_flag=official,
            latest_official_month=last_official.month if last_official else None,
            latest_official_flag=last_official.flag if last_official else None,
            runs=runs,
            notice=(
                "A previsão é uma aproximação: não temos as rodadas do DECOMP nem a previsão de "
                "geração hidrelétrica do ONS."
                if runs
                else NOT_PUBLISHED
            ),
            disclaimer=DISCLAIMER,
            attribution=ATTRIBUTION,
        )

    return cache.get_or_set(load)


@router.get("/scoreboard", response_model=FlagScoreboardResponse)
def flag_scoreboard(session: SessionDep, cache: PublicCacheDep) -> FlagScoreboardResponse:
    """Forecast against the flag announced, per run and per lead. Rows are never rewritten."""

    def load() -> FlagScoreboardResponse:
        rows = session.execute(
            select(FlagForecastRun, FlagForecastScore)
            .join(FlagForecastScore, FlagForecastScore.run_id == FlagForecastRun.id)
            .where(FlagForecastRun.status == "ready")
            .order_by(FlagForecastRun.target_month.desc(), FlagForecastRun.lead_days.desc())
        ).all()
        items = [
            FlagScoreItem(
                target_month=run.target_month,
                lead_days=run.lead_days,
                generated_at=run.generated_at,
                actual_flag=score.actual_flag,
                prob_actual=float(score.prob_actual),
                brier=float(score.brier),
                top_hit=score.top_hit,
            )
            for run, score in rows
        ]
        by_lead: dict[int, list[FlagScoreItem]] = defaultdict(list)
        for item in items:
            by_lead[item.lead_days].append(item)
        summary = [
            FlagScoreSummary(
                lead_days=lead,
                n=len(group),
                mean_brier=round(sum(i.brier for i in group) / len(group), 6),
                hit_rate=round(sum(i.top_hit for i in group) / len(group), 4),
            )
            for lead, group in sorted(by_lead.items(), reverse=True)
        ]
        return FlagScoreboardResponse(
            items=items,
            summary=summary,
            notice=(
                "O placar começa no primeiro mês previsto e cada linha é gravada uma vez, "
                "com a data da previsão."
                if items
                else "Ainda não há previsões publicadas para pontuar."
            ),
        )

    return cache.get_or_set(load)
