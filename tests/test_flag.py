from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.cache import PUBLIC_CACHE_CONTROL
from app.models import (
    FlagForecastProb,
    FlagForecastRun,
    FlagForecastScore,
    FlagRuleMonth,
    TariffFlagMonthly,
)


def rule_row(
    month: date, flag: str, trigger: str, gsf: str, bands: tuple[str, str, str]
) -> FlagRuleMonth:
    return FlagRuleMonth(
        month=month,
        rule_version="C",
        pld_min_brl_per_mwh=Decimal("57.31"),
        pld_max_brl_per_mwh=Decimal("785.27"),
        gh_mwmed=Decimal("37885"),
        gf_mwmed=Decimal("52911"),
        gsf=Decimal(gsf),
        pld_trigger_brl_per_mwh=Decimal(trigger),
        gfom_mwmed=Decimal("0"),
        green_upper_brl_per_mwh=Decimal(bands[0]),
        yellow_upper_brl_per_mwh=Decimal(bands[1]),
        red1_upper_brl_per_mwh=Decimal(bands[2]),
        flag=flag,
        bulletin_number=100,
        bulletin_url="https://www.ccee.org.br/documents/x.pdf",
        bulletin_published_on=date(2026, 8, 6),
    )


@pytest.fixture
def rules(session: Session) -> None:
    session.add_all(
        [
            rule_row(date(2026, 7, 1), "Amarela", "171.48", "0.70", ("91.60", "229.97", "316.84")),
            rule_row(date(2026, 8, 1), "Amarela", "128.67", "0.72", ("98.14", "246.40", "339.47")),
            TariffFlagMonthly(
                month=date(2026, 8, 1), flag="Amarela", additional_brl_per_mwh=Decimal("18.85")
            ),
            TariffFlagMonthly(
                month=date(2026, 9, 1), flag="Verde", additional_brl_per_mwh=Decimal("0")
            ),
        ]
    )
    session.commit()


def add_run(
    session: Session, month: date, lead: int, probs: dict[str, float], status: str = "ready"
) -> int:
    run = FlagForecastRun(
        target_month=month,
        lead_days=lead,
        generated_at=datetime(2026, 8, 31 - lead // 7, 12, tzinfo=UTC),
        data_through=date(2026, 8, 25),
        model_version="ridge-test",
        rule_version="C",
        trigger_p10_brl_per_mwh=Decimal("90"),
        trigger_p50_brl_per_mwh=Decimal("130"),
        trigger_p90_brl_per_mwh=Decimal("260"),
        status=status,
    )
    session.add(run)
    session.flush()
    edges = {
        "Verde": ("57.31", "98.14"),
        "Amarela": ("98.15", "246.40"),
        "Vermelha P1": ("246.41", "339.47"),
        "Vermelha P2": ("339.48", "785.27"),
    }
    for flag, prob in probs.items():
        session.add(
            FlagForecastProb(
                run_id=run.id,
                flag=flag,
                prob=Decimal(str(prob)),
                band_lower_brl_per_mwh=Decimal(edges[flag][0]),
                band_upper_brl_per_mwh=Decimal(edges[flag][1]),
            )
        )
    session.commit()
    return run.id


def test_rule_serves_constants_formula_and_the_latest_month(
    client: TestClient, rules: None
) -> None:
    response = client.get("/v1/flag/rule")
    assert response.status_code == 200
    assert response.headers["cache-control"] == PUBLIC_CACHE_CONTROL
    body = response.json()
    assert [v["name"] for v in body["versions"]] == ["B", "C"]
    assert body["versions"][1]["lim_green"] == pytest.approx(27.4798)
    assert "adjusted" in body["versions"][1]["status"]
    assert body["gfom"][0]["original"] == "Verde"
    assert body["latest_month"] == "2026-08-01"
    assert body["gsf"] == 0.72
    assert body["green_upper_brl_per_mwh"] == 98.14
    assert "parecer jurídico" in body["attribution"]["legal_note"]


def test_rule_without_any_month_still_serves_the_constants(client: TestClient) -> None:
    body = client.get("/v1/flag/rule").json()
    assert body["latest_month"] is None and body["gsf"] is None
    assert len(body["versions"]) == 2


def test_months_are_filtered_and_carry_the_bulletin_reference(
    client: TestClient, rules: None
) -> None:
    body = client.get("/v1/flag/months").json()
    assert [m["month"] for m in body["items"]] == ["2026-07-01", "2026-08-01"]
    first = body["items"][1]
    assert first["pld_trigger_brl_per_mwh"] == 128.67
    assert first["bulletin_number"] == 100
    assert client.get("/v1/flag/months?from=2026-08-01").json()["items"][0]["month"] == "2026-08-01"
    assert client.get("/v1/flag/months?to=2026-07-31").json()["items"][0]["month"] == "2026-07-01"


def test_forecast_is_not_published_without_runs(client: TestClient, rules: None) -> None:
    body = client.get("/v1/flag/forecast").json()
    assert body["published"] is False
    assert body["runs"] == []
    assert "em avaliação" in body["notice"]
    assert body["latest_official_month"] == "2026-09-01"
    assert body["latest_official_flag"] == "Verde"
    assert "não é a decisão da ANEEL" in body["disclaimer"]


def test_forecast_shows_only_ready_runs_newest_per_lead(
    client: TestClient, session: Session, rules: None
) -> None:
    add_run(
        session,
        date(2026, 9, 1),
        14,
        {"Verde": 0.6, "Amarela": 0.3, "Vermelha P1": 0.1, "Vermelha P2": 0.0},
    )
    add_run(
        session,
        date(2026, 9, 1),
        7,
        {"Verde": 0.7, "Amarela": 0.2, "Vermelha P1": 0.1, "Vermelha P2": 0.0},
    )
    add_run(
        session,
        date(2026, 9, 1),
        3,
        {"Verde": 1.0, "Amarela": 0.0, "Vermelha P1": 0.0, "Vermelha P2": 0.0},
        status="loading",
    )
    body = client.get("/v1/flag/forecast").json()
    assert body["published"] is True
    assert body["target_month"] == "2026-09-01"
    assert body["official_flag"] == "Verde"
    assert [r["lead_days"] for r in body["runs"]] == [14, 7]
    probs = body["runs"][0]["probabilities"]
    assert [p["flag"] for p in probs] == ["Verde", "Amarela", "Vermelha P1", "Vermelha P2"]
    assert sum(p["prob"] for p in probs) == pytest.approx(1.0)
    assert body["runs"][0]["trigger_p50_brl_per_mwh"] == 130.0
    assert body["runs"][0]["data_through"] == "2026-08-25"
    assert "DECOMP" in body["notice"]


def test_scoreboard_is_empty_before_the_first_score(client: TestClient, rules: None) -> None:
    empty = client.get("/v1/flag/scoreboard").json()
    assert empty["items"] == []
    assert empty["summary"] == []
    assert "Ainda não" in empty["notice"]


def test_scoreboard_summarises_per_lead(client: TestClient, session: Session, rules: None) -> None:
    for month, actual, brier, hit in (
        (date(2026, 8, 1), "Amarela", "0.20", True),
        (date(2026, 9, 1), "Verde", "0.50", False),
    ):
        run_id = add_run(
            session,
            month,
            14,
            {"Verde": 0.5, "Amarela": 0.5, "Vermelha P1": 0.0, "Vermelha P2": 0.0},
        )
        session.add(
            FlagForecastScore(
                run_id=run_id,
                actual_flag=actual,
                prob_actual=Decimal("0.5"),
                brier=Decimal(brier),
                top_hit=hit,
            )
        )
    session.commit()
    body = client.get("/v1/flag/scoreboard").json()
    assert [i["target_month"] for i in body["items"]] == ["2026-09-01", "2026-08-01"]
    assert body["summary"] == [{"lead_days": 14, "n": 2, "mean_brier": 0.35, "hit_rate": 0.5}]


def test_unknown_month_filter_is_rejected(client: TestClient) -> None:
    assert client.get("/v1/flag/months?from=nope").status_code == 422
