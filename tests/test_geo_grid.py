from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.cache import PUBLIC_CACHE_CONTROL
from app.models import Substation, TransmissionLine

JAN = date(2026, 1, 10)


def _sub(
    station: str, name: str, state: str, kv: str, lat: str | None, lon: str | None
) -> Substation:
    return Substation(
        station_id=station,
        valid_from=JAN,
        row_hash=f"h-{station}",
        substation_id=station[:5],
        name=name,
        voltage_kv=Decimal(kv),
        state=state,
        subsystem="NE",
        latitude=None if lat is None else Decimal(lat),
        longitude=None if lon is None else Decimal(lon),
    )


def _line(code: str, kv: str, a: str, b: str, sa: str, sb: str, **kw: object) -> TransmissionLine:
    values: dict[str, object] = {
        "equipment_code": code,
        "valid_from": JAN,
        "row_hash": f"h-{code}",
        "name": f"LT {kv} kV {a} / {b}",
        "voltage_kv": Decimal(kv),
        "from_substation": a,
        "to_substation": b,
        "from_state": sa,
        "to_state": sb,
        "length_km": Decimal("100"),
    }
    values.update(kw)
    return TransmissionLine(**values)


@pytest.fixture
def grid_geo_seed(session: Session) -> None:
    session.add_all(
        [
            _sub("A5", "ALFA", "BA", "500", "-10.0", "-40.0"),
            _sub("A2", "ALFA", "BA", "230", "-10.0", "-40.0"),  # same place, other voltage
            _sub("B5", "BETA", "PE", "500", "-8.0", "-37.0"),
            _sub("C2", "GAMA", "CE", "230", "-4.0", "-39.0"),
            _sub("D2", "DELTA", "CE", "230", None, None),  # no position
            _sub("E1", "REPETIDA", "SP", "138", "-23.0", "-46.0"),
            _sub("E2", "REPETIDA", "SP", "138", "-22.0", "-47.0"),  # two places, same name
            _sub("F1", "FIM", "SP", "138", "-21.0", "-45.0"),
            _sub("Z0", "ANTIGA", "BA", "500", "-1.0", "-1.0"),
        ]
    )
    session.add(
        Substation(
            station_id="OLD",
            valid_from=date(2025, 1, 1),
            valid_to=JAN,
            row_hash="old",
            name="HISTORICA",
            voltage_kv=Decimal("500"),
            latitude=Decimal("1"),
            longitude=Decimal("1"),
        )
    )
    session.add_all(
        [
            _line("L1", "500", "ALFA", "BETA", "BA", "PE"),
            _line("L2", "230", "ALFA", "GAMA", "BA", "CE"),
            _line("L3", "230", "ALFA", "DELTA", "BA", "CE"),  # DELTA has no position
            _line("L4", "138", "REPETIDA", "FIM", "SP", "SP"),  # ambiguous name: not guessed
            _line("L5", "500", "ALFA", "BETA", "BA", "PE", valid_to=JAN),  # old version
            _line("L6", "230", "NAOEXISTE", "BETA", "BA", "PE"),
        ]
    )
    session.commit()


pytestmark = pytest.mark.usefixtures("grid_geo_seed")


def test_substations_only_current_ones_with_a_position(client: TestClient) -> None:
    r = client.get("/v1/geo/substations")
    assert r.status_code == 200
    assert r.headers["cache-control"] == PUBLIC_CACHE_CONTROL
    body = r.json()
    assert body["type"] == "FeatureCollection"
    assert body["meta"]["total"] == 9
    assert body["meta"]["omitted"] == 1
    stations = [f["properties"]["station_id"] for f in body["features"]]
    assert "D2" not in stations and "OLD" not in stations
    assert stations[0] in {"A5", "B5", "Z0"}  # highest voltage first
    first = body["features"][0]
    assert first["geometry"]["type"] == "Point"
    assert set(first["properties"]) == {
        "station_id",
        "substation_id",
        "name",
        "voltage_kv",
        "subsystem",
        "state",
        "main_agent",
    }


def test_substations_filters(client: TestClient) -> None:
    body = client.get("/v1/geo/substations", params={"voltage_min": 500}).json()
    assert {f["properties"]["voltage_kv"] for f in body["features"]} == {500.0}
    body = client.get("/v1/geo/substations", params={"state": "ce"}).json()
    assert [f["properties"]["station_id"] for f in body["features"]] == ["C2"]
    assert client.get("/v1/geo/substations", params={"state": "BAH"}).status_code == 422


def test_lines_are_schematic_segments_between_the_substations(client: TestClient) -> None:
    body = client.get("/v1/geo/lines").json()
    codes = {f["properties"]["equipment_code"] for f in body["features"]}
    assert codes == {"L1", "L2"}
    assert body["meta"]["total"] == 5
    assert body["meta"]["omitted"] == 3  # no position, ambiguous name, unknown name
    assert any("Esquemático" in w for w in body["meta"]["warnings"])
    line = next(f for f in body["features"] if f["properties"]["equipment_code"] == "L1")
    assert line["geometry"] == {
        "type": "LineString",
        "coordinates": [[-40.0, -10.0], [-37.0, -8.0]],
    }
    assert line["properties"]["geometry_kind"] == "schematic"
    assert line["properties"]["voltage_kv"] == 500.0


def test_lines_filters(client: TestClient) -> None:
    body = client.get("/v1/geo/lines", params={"voltage_min": 500}).json()
    assert [f["properties"]["equipment_code"] for f in body["features"]] == ["L1"]
    body = client.get("/v1/geo/lines", params={"state": "CE"}).json()
    assert [f["properties"]["equipment_code"] for f in body["features"]] == ["L2"]
