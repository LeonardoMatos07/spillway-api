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


class PlantGeoProperties(BaseModel):
    id: str
    slug: str
    name: str
    source: Literal["wind", "solar"]
    state: str
    subsystem: str
    capacity_mw: float | None
    connection_point: str | None
    # "substation": position of the substation it connects to (approximate); "official": a point
    # published by the regulator.
    location_precision: Literal["substation", "official"]
    matched_on: str | None
    month: date | None
    curtailed_mwh: float | None
    curtailment_pct: float | None
    estimated_loss_brl: float | None


class PlantGeoFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    geometry: GeoPoint
    properties: PlantGeoProperties


class UnlocatedPlant(BaseModel):
    """A plant with no position: it is not a feature, but the map lists it."""

    id: str
    slug: str
    name: str
    source: Literal["wind", "solar"]
    state: str
    capacity_mw: float | None
    connection_point: str | None
    curtailed_mwh: float | None


class PlantGeoCollection(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    meta: GeoMeta
    features: list[PlantGeoFeature]
    unlocated: list[UnlocatedPlant]
