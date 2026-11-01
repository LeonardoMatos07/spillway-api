import json
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any, cast

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import SubsystemMonthlyCurtailment
from tests.conftest import M2M_CLIENT, make_settings

LOAD_RUNS = "/v1/admin/load-runs"
ADMIN_REPORTS = "/v1/admin/reports"
REVALIDATE = "/v1/admin/revalidate"


def test_missing_token_401(client: TestClient) -> None:
    r = client.get(LOAD_RUNS)
    assert r.status_code == 401
    assert r.json() == {"detail": "Authentication required."}
    assert r.headers["www-authenticate"] == "Bearer"


def test_wrong_group_403(client: TestClient, make_token: Callable[..., str]) -> None:
    token = make_token(**{"cognito:groups": ["reader"]})
    r = client.get(LOAD_RUNS, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


def test_admin_group_ok(client: TestClient, admin_headers: dict[str, str]) -> None:
    r = client.get(LOAD_RUNS, headers=admin_headers)
    assert r.status_code == 200
    assert r.json() == {"items": []}


def test_m2m_scope_ok(client: TestClient, make_token: Callable[..., str]) -> None:
    token = make_token(client_id=M2M_CLIENT, sub=M2M_CLIENT, scope="energia-api/admin")
    r = client.get(LOAD_RUNS, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200


def test_m2m_other_scope_403(client: TestClient, make_token: Callable[..., str]) -> None:
    token = make_token(client_id=M2M_CLIENT, scope="energia-api/read")
    r = client.get(LOAD_RUNS, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


@pytest.mark.parametrize(
    "claims",
    [
        {"token_use": "id"},
        {"client_id": "other-client"},
        {"iss": "https://cognito-idp.sa-east-1.amazonaws.com/other-pool"},
        {"exp": 1_000_000},
        {"token_use": None},
        {"kid": "unknown-key"},
    ],
)
def test_invalid_tokens_401(
    client: TestClient, make_token: Callable[..., str], claims: dict[str, Any]
) -> None:
    claims = {"cognito:groups": ["admin"], **claims}
    if "exp" in claims:
        claims["iat"] = claims["exp"] - 60
    token = make_token(**claims)
    r = client.get(LOAD_RUNS, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


def test_wrong_signing_key_401(client: TestClient, make_token: Callable[..., str]) -> None:
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = make_token(key=other, **{"cognito:groups": ["admin"]})
    r = client.get(LOAD_RUNS, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


def test_garbage_token_401(client: TestClient) -> None:
    r = client.get(LOAD_RUNS, headers={"Authorization": "Bearer not.a.jwt"})
    assert r.status_code == 401


def test_jwks_is_cached(
    app_factory: Callable[..., TestClient],
    jwks: dict[str, Any],
    admin_headers: dict[str, str],
) -> None:
    client = app_factory()
    calls: list[str] = []

    def fetcher(url: str) -> dict[str, Any]:
        calls.append(url)
        return jwks

    cast(FastAPI, client.app).state.jwks.fetcher = fetcher
    for _ in range(3):
        assert client.get(LOAD_RUNS, headers=admin_headers).status_code == 200
    assert calls == [
        "https://cognito-idp.sa-east-1.amazonaws.com/sa-east-1_TESTPOOL/.well-known/jwks.json"
    ]


def test_auth_disabled_requires_local() -> None:
    with pytest.raises(ValidationError, match="AUTH_DISABLED"):
        make_settings(ENVIRONMENT="prod", AUTH_DISABLED=True)


def test_prod_requires_cognito() -> None:
    with pytest.raises(ValidationError, match="COGNITO_USER_POOL_ID"):
        make_settings(ENVIRONMENT="prod", COGNITO_USER_POOL_ID="")


def test_auth_disabled_local_allows_admin(app_factory: Callable[..., TestClient]) -> None:
    client = app_factory(AUTH_DISABLED=True)
    assert client.get(LOAD_RUNS).status_code == 200


def test_database_url_normalized() -> None:
    s = Settings(_env_file=None, DATABASE_URL="postgresql://u:p@h:5432/d")
    assert s.database_url == "postgresql+psycopg://u:p@h:5432/d"


@pytest.mark.usefixtures("seed")
def test_load_runs(client: TestClient, admin_headers: dict[str, str]) -> None:
    items = client.get(LOAD_RUNS, headers=admin_headers).json()["items"]
    assert [i["dataset"] for i in items] == ["aggregates", "wind_plant_curtailment"]
    assert set(items[0]) == {
        "id",
        "dataset",
        "period",
        "source_file",
        "checksum",
        "row_count",
        "started_at",
        "finished_at",
        "status",
        "detail",
    }
    assert items[0]["period"] == "2026-09"
    limited = client.get(LOAD_RUNS, params={"limit": 1}, headers=admin_headers)
    assert len(limited.json()["items"]) == 1


@pytest.mark.usefixtures("seed")
def test_admin_reports_lists_drafts(client: TestClient, admin_headers: dict[str, str]) -> None:
    items = client.get(ADMIN_REPORTS, headers=admin_headers).json()["items"]
    assert {i["slug"] for i in items} == {"report-august-2026", "report-september-2026"}


def test_upsert_report(client: TestClient, admin_headers: dict[str, str]) -> None:
    body = {"month": "2026-09", "title": "Curtailment in September", "content": "# Text"}
    r = client.post(ADMIN_REPORTS, json={**body, "publish": False}, headers=admin_headers)
    assert r.status_code == 200
    created = r.json()
    assert created["slug"] == "curtailment-in-september"
    assert created["month"] == "2026-09"
    assert created["published_at"] is None
    assert client.get("/v1/reports/curtailment-in-september").status_code == 404

    r = client.post(ADMIN_REPORTS, json={**body, "publish": True}, headers=admin_headers)
    published = r.json()
    assert published["published_at"] is not None
    assert client.get("/v1/reports/curtailment-in-september").status_code == 200

    r = client.post(
        ADMIN_REPORTS,
        json={**body, "summary": "new", "publish": True},
        headers=admin_headers,
    )
    assert r.json()["published_at"] == published["published_at"]
    assert r.json()["summary"] == "new"
    assert len(client.get(ADMIN_REPORTS, headers=admin_headers).json()["items"]) == 1

    r = client.post(
        ADMIN_REPORTS,
        json={**body, "slug": "Invalid Slug", "publish": True},
        headers=admin_headers,
    )
    assert r.status_code == 422


def test_upsert_report_requires_admin(client: TestClient) -> None:
    body = {"month": "2026-09", "title": "x", "content": "y", "publish": True}
    assert client.post(ADMIN_REPORTS, json=body).status_code == 401


def _add_sin_row(session: Session, month: date) -> None:
    session.add(
        SubsystemMonthlyCurtailment(
            subsystem="SIN",
            source="total",
            month=month,
            verified_generation_mwh=Decimal(1),
            curtailed_mwh=Decimal(1),
            curtailed_rel_mwh=Decimal(0),
            curtailed_cnf_mwh=Decimal(0),
            curtailed_ene_mwh=Decimal(0),
            curtailed_other_mwh=Decimal(0),
            affected_plants=0,
        )
    )
    session.commit()


@pytest.mark.usefixtures("seed")
def test_cache_and_revalidate(
    client: TestClient,
    session: Session,
    admin_headers: dict[str, str],
    web_calls: list[httpx.Request],
) -> None:
    before = client.get("/v1/months").json()["months"]
    _add_sin_row(session, date(2026, 10, 1))
    assert client.get("/v1/months").json()["months"] == before

    r = client.post(REVALIDATE, json={"tags": ["curtailment", "plants"]}, headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["tags"] == ["curtailment", "plants"]
    assert body["cache_cleared"] is True and body["entries_removed"] >= 1
    assert body["web_revalidated"] is True and body["detail"] is None

    assert len(web_calls) == 1
    call = web_calls[0]
    assert str(call.url) == "http://web.test/api/revalidate"
    assert call.headers["x-revalidate-secret"] == "test-secret"
    assert json.loads(call.content) == {"tags": ["curtailment", "plants"]}

    assert client.get("/v1/months").json()["months"][0] == "2026-10"


def test_revalidate_default_tags(
    client: TestClient, admin_headers: dict[str, str], web_calls: list[httpx.Request]
) -> None:
    r = client.post(REVALIDATE, headers=admin_headers)
    all_tags = [
        "curtailment",
        "plants",
        "reports",
        "forecast",
        "news",
        "market",
        "reliability",
        "flag",
    ]
    assert r.json()["tags"] == all_tags
    assert json.loads(web_calls[0].content) == {"tags": all_tags}


def test_revalidate_forecast_tag_clears_the_cache(
    client: TestClient, admin_headers: dict[str, str], web_calls: list[httpx.Request]
) -> None:
    r = client.post(REVALIDATE, json={"tags": ["forecast"]}, headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["tags"] == ["forecast"] and body["cache_cleared"] is True
    assert json.loads(web_calls[0].content) == {"tags": ["forecast"]}


def test_revalidate_unknown_tag(client: TestClient, admin_headers: dict[str, str]) -> None:
    r = client.post(REVALIDATE, json={"tags": ["other"]}, headers=admin_headers)
    assert r.status_code == 422


def test_revalidate_web_unreachable(
    app_factory: Callable[..., TestClient], admin_headers: dict[str, str]
) -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client = app_factory(transport=httpx.MockTransport(fail))
    r = client.post(REVALIDATE, headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["cache_cleared"] is True
    assert body["web_revalidated"] is False
    assert "ConnectError" in body["detail"]


def test_revalidate_web_error_status(
    app_factory: Callable[..., TestClient], admin_headers: dict[str, str]
) -> None:
    client = app_factory(transport=httpx.MockTransport(lambda req: httpx.Response(401)))
    body = client.post(REVALIDATE, headers=admin_headers).json()
    assert body["web_revalidated"] is False


def test_revalidate_without_secret(
    app_factory: Callable[..., TestClient],
    admin_headers: dict[str, str],
    web_calls: list[httpx.Request],
) -> None:
    client = app_factory(REVALIDATE_SECRET="")
    body = client.post(REVALIDATE, headers=admin_headers).json()
    assert body["web_revalidated"] is False and web_calls == []
