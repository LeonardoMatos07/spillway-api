from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.cache import PUBLIC_CACHE_CONTROL
from app.models import Reservoir, ReservoirDaily


@pytest.fixture
def reservoir_seed(session: Session) -> None:
    session.add_all(
        [
            Reservoir(
                id="GRAVER",
                name="A. VERMELHA",
                slug="a-vermelha-graver",
                subsystem="SE",
                basin="GRANDE",
                river="GRANDE",
                useful_volume_hm3=Decimal("5856"),
                latitude=Decimal("-19.87"),
                longitude=Decimal("-50.35"),
            ),
            Reservoir(id="SEMPOS", name="SEM POSICAO", slug="sem-posicao", subsystem="NE"),
            Reservoir(
                id="NEPOS",
                name="NORDESTE",
                slug="nordeste",
                subsystem="NE",
                latitude=Decimal("-9.4"),
                longitude=Decimal("-40.8"),
            ),
        ]
    )
    session.flush()
    for day in (1, 2):
        session.add(
            ReservoirDaily(
                day=date(2026, 9, day),
                reservoir_id="GRAVER",
                storage_pct=Decimal("27.5") + day,
                ena_storable_pct_mlt=Decimal("80"),
            )
        )
    session.commit()


pytestmark = pytest.mark.usefixtures("reservoir_seed")


def test_reservoirs_are_a_feature_collection_of_the_latest_day(client: TestClient) -> None:
    r = client.get("/v1/geo/reservoirs")
    assert r.status_code == 200
    assert r.headers["cache-control"] == PUBLIC_CACHE_CONTROL
    body = r.json()
    assert body["type"] == "FeatureCollection"
    assert body["meta"]["as_of"] == "2026-09-02"
    assert body["meta"]["total"] == 3
    assert body["meta"]["omitted"] == 1  # no coordinates: not a feature
    assert body["meta"]["warnings"]
    by_slug = {f["properties"]["slug"]: f for f in body["features"]}
    assert set(by_slug) == {"a-vermelha-graver", "nordeste"}
    feature = by_slug["a-vermelha-graver"]
    assert feature["type"] == "Feature"
    assert feature["geometry"] == {"type": "Point", "coordinates": [-50.35, -19.87]}
    assert feature["properties"]["storage_pct"] == 29.5
    assert feature["properties"]["useful_volume_hm3"] == 5856.0
    assert by_slug["nordeste"]["properties"]["storage_pct"] is None


def test_reservoirs_by_day_and_subsystem(client: TestClient) -> None:
    body = client.get("/v1/geo/reservoirs", params={"date": "2026-09-01"}).json()
    props = {f["properties"]["slug"]: f["properties"] for f in body["features"]}
    assert props["a-vermelha-graver"]["storage_pct"] == 28.5
    body = client.get("/v1/geo/reservoirs", params={"subsystem": "NE"}).json()
    assert [f["properties"]["slug"] for f in body["features"]] == ["nordeste"]
    assert body["meta"]["total"] == 2


def test_reservoirs_day_without_data_is_404(client: TestClient) -> None:
    assert client.get("/v1/geo/reservoirs", params={"date": "2020-01-01"}).status_code == 404
    assert client.get("/v1/geo/reservoirs", params={"date": "x"}).status_code == 422
