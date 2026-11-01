from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.cache import PUBLIC_CACHE_CONTROL
from app.models import PlantLocation


@pytest.fixture
def located(session: Session, seed: None) -> None:
    session.add_all(
        [
            PlantLocation(
                plant_id="BAU1",
                latitude=Decimal("-10.5"),
                longitude=Decimal("-41.2"),
                location_precision="substation",
                source="ons-substation",
                matched_on="BAU SE|BA|230",
            ),
            PlantLocation(
                plant_id="RNU1",
                latitude=Decimal("-5.8"),
                longitude=Decimal("-36.2"),
                location_precision="official",
                source="aneel-sigel",
            ),
            # a cluster is never drawn
            PlantLocation(
                plant_id="CJU_BA1",
                latitude=Decimal("-10.0"),
                longitude=Decimal("-41.0"),
                location_precision="substation",
                source="ons-substation",
            ),
        ]
    )
    session.commit()


pytestmark = pytest.mark.usefixtures("located")


def test_plants_with_position_and_the_latest_month(client: TestClient) -> None:
    r = client.get("/v1/geo/plants")
    assert r.status_code == 200
    assert r.headers["cache-control"] == PUBLIC_CACHE_CONTROL
    body = r.json()
    assert body["type"] == "FeatureCollection"
    assert body["meta"]["as_of"] == "2026-09-01"
    assert body["meta"]["total"] == 4  # the cluster is not a plant
    assert body["meta"]["omitted"] == 2
    assert any("aproximada" in w for w in body["meta"]["warnings"])
    by_id = {f["properties"]["id"]: f for f in body["features"]}
    assert set(by_id) == {"BAU1", "RNU1"}
    first = by_id["BAU1"]
    assert first["geometry"] == {"type": "Point", "coordinates": [-41.2, -10.5]}
    assert first["properties"]["location_precision"] == "substation"
    assert first["properties"]["matched_on"] == "BAU SE|BA|230"
    assert first["properties"]["curtailed_mwh"] == 500.0
    assert first["properties"]["curtailment_pct"] == 10.5
    assert by_id["RNU1"]["properties"]["location_precision"] == "official"


def test_plants_without_position_are_listed_apart(client: TestClient) -> None:
    body = client.get("/v1/geo/plants").json()
    assert {p["id"] for p in body["unlocated"]} == {"BAU2", "BAS1"}
    assert all("geometry" not in p for p in body["unlocated"])


def test_plants_month_source_and_state(client: TestClient) -> None:
    body = client.get("/v1/geo/plants", params={"month": "2026-08"}).json()
    props = {f["properties"]["id"]: f["properties"] for f in body["features"]}
    assert props["BAU1"]["curtailed_mwh"] == 100.0
    assert props["RNU1"]["curtailed_mwh"] is None  # no row for that month
    body = client.get("/v1/geo/plants", params={"source": "solar"}).json()
    assert body["features"] == []
    assert [p["id"] for p in body["unlocated"]] == ["BAS1"]
    body = client.get("/v1/geo/plants", params={"state": "rn"}).json()
    assert [f["properties"]["id"] for f in body["features"]] == ["RNU1"]


def test_plants_bad_input(client: TestClient) -> None:
    assert client.get("/v1/geo/plants", params={"month": "2026-13"}).status_code == 422
    assert client.get("/v1/geo/plants", params={"state": "XX"}).status_code == 404
    assert client.get("/v1/geo/plants", params={"source": "coal"}).status_code == 422


def test_plants_one_by_slug(client: TestClient) -> None:
    body = client.get("/v1/geo/plants", params={"slug": "alpha-i-bau1"}).json()
    assert [f["properties"]["id"] for f in body["features"]] == ["BAU1"]
    assert body["unlocated"] == []
    body = client.get("/v1/geo/plants", params={"slug": "alpha-ii-bau2"}).json()
    assert body["features"] == [] and [p["id"] for p in body["unlocated"]] == ["BAU2"]
    body = client.get("/v1/geo/plants", params={"slug": "nao-existe"}).json()
    assert body["features"] == [] and body["unlocated"] == [] and body["meta"]["total"] == 0
