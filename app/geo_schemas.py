"""GeoJSON envelopes of the map layers: FeatureCollection plus `meta` (source, license, notes)."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel


class GeoMeta(BaseModel):
    """Where a layer comes from. `omitted` counts the rows left out because they lack a position."""

    source_name: str
    source_url: str
    license: str
    as_of: date | None
    updated_at: datetime | None
    warnings: list[str]
    total: int
    omitted: int


class GeoPoint(BaseModel):
    type: Literal["Point"] = "Point"
    coordinates: tuple[float, float]  # longitude, latitude


class ReservoirProperties(BaseModel):
    slug: str
    name: str
    plant_name: str | None
    subsystem: str | None
    basin: str | None
    river: str | None
    useful_volume_hm3: float | None
    storage_pct: float | None
    ena_storable_pct_mlt: float | None
    day: date | None


class ReservoirFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    geometry: GeoPoint
    properties: ReservoirProperties


class ReservoirCollection(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    meta: GeoMeta
    features: list[ReservoirFeature]


class GeoLine(BaseModel):
    type: Literal["LineString"] = "LineString"
    coordinates: list[tuple[float, float]]  # longitude, latitude


class SubstationProperties(BaseModel):
    station_id: str
    substation_id: str | None
    name: str | None
    voltage_kv: float | None
    subsystem: str | None
    state: str | None
    main_agent: str | None


class SubstationFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    geometry: GeoPoint
    properties: SubstationProperties


class SubstationCollection(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    meta: GeoMeta
    features: list[SubstationFeature]


class LineProperties(BaseModel):
    equipment_code: str
    name: str | None
    voltage_kv: float | None
    length_km: float | None
    from_substation: str | None
    to_substation: str | None
    from_state: str | None
    to_state: str | None
    # Always "schematic": a straight segment between the two substations, not the real route.
    geometry_kind: Literal["schematic"] = "schematic"


class LineFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    geometry: GeoLine
    properties: LineProperties


class LineCollection(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    meta: GeoMeta
    features: list[LineFeature]
