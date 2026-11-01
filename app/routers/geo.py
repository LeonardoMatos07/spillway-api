"""Map layers: values per place, without geometry (the web draws the outlines itself)."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, or_, select

from app.cache import PublicCacheDep
from app.db import SessionDep
from app.geo_schemas import (
    GeoLine,
    GeoMeta,
    GeoPoint,
    LineCollection,
    LineFeature,
    LineProperties,
    PlantGeoCollection,
    PlantGeoFeature,
    PlantGeoProperties,
    ReservoirCollection,
    ReservoirFeature,
    ReservoirProperties,
    SubstationCollection,
    SubstationFeature,
    SubstationProperties,
    UnlocatedPlant,
)
from app.models import (
    Plant,
    PlantLocation,
    PlantMonthlyCurtailment,
    Reservoir,
    ReservoirDaily,
    StateMonthlyCurtailment,
    Substation,
    TransmissionLine,
)
from app.queries import latest_plant_month
from app.routers.curtailment import STATES, MonthQuery
from app.schemas import (
    AggregateSource,
    GeoStateCurtailment,
    GeoStatesMeta,
    GeoStatesResponse,
    parse_month,
)

router = APIRouter(prefix="/v1/geo", tags=["geo"])

ONS_LICENSE = "Termos de uso de cada conjunto em dados.ons.org.br; processado pelo Spillway."

STATES_WARNINGS = (
    "Valores por unidade da federação, somados a partir das usinas eólicas e solares despachadas "
    "pelo ONS; estados sem essas usinas não aparecem.",
    "A porcentagem é a energia cortada sobre a energia que a usina teria gerado (verificada mais "
    "cortada).",
)


@router.get("/states/curtailment", response_model=GeoStatesResponse)
def states_curtailment(
    session: SessionDep,
    cache: PublicCacheDep,
    source: Annotated[AggregateSource, Query()] = "total",
    month: MonthQuery = None,
) -> GeoStatesResponse:
    """Curtailment of one month per state. Same data as `/v1/curtailment/states/{state}`."""

    def load() -> GeoStatesResponse:
        months = [
            m
            for m in session.scalars(
                select(StateMonthlyCurtailment.month)
                .where(StateMonthlyCurtailment.source == source)
                .distinct()
                .order_by(StateMonthlyCurtailment.month.desc())
            )
        ]
        if not months:
            return _response(source, None, [], [], None)
        chosen = parse_month(month) if month is not None else months[0]
        if chosen not in months:
            raise HTTPException(status_code=404, detail="No data for this month.")
        rows = session.scalars(
            select(StateMonthlyCurtailment)
            .where(
                StateMonthlyCurtailment.source == source,
                StateMonthlyCurtailment.month == chosen,
                StateMonthlyCurtailment.state.in_(STATES),
            )
            .order_by(StateMonthlyCurtailment.state)
        ).all()
        updated = session.scalar(
            select(func.max(StateMonthlyCurtailment.updated_at)).where(
                StateMonthlyCurtailment.source == source,
                StateMonthlyCurtailment.month == chosen,
            )
        )
        items = [
            GeoStateCurtailment(
                state=r.state,
                curtailment_pct=None if r.curtailment_pct is None else float(r.curtailment_pct),
                curtailed_mwh=float(r.curtailed_mwh),
                verified_generation_mwh=float(r.verified_generation_mwh),
                estimated_loss_brl=(
                    None if r.estimated_loss_brl is None else float(r.estimated_loss_brl)
                ),
                affected_plants=r.affected_plants,
            )
            for r in rows
        ]
        return _response(source, chosen, items, months, updated)

    return cache.get_or_set(load)


def _response(
    source: AggregateSource,
    month: date | None,
    items: list[GeoStateCurtailment],
    months: list[date],
    updated: datetime | None,
) -> GeoStatesResponse:
    present = {i.state for i in items}
    return GeoStatesResponse(
        meta=GeoStatesMeta(
            source_name="Operador Nacional do Sistema Elétrico (ONS), dados abertos",
            source_url="https://dados.ons.org.br/",
            license=ONS_LICENSE,
            data_source=source,
            month=month,
            months=sorted(months),
            updated_at=(updated if updated is None else updated.astimezone(UTC)),
            warnings=list(STATES_WARNINGS),
            omitted=len(STATES) - len(present) if month is not None else len(STATES),
            omitted_states=sorted(STATES - present),
        ),
        items=items,
    )


RESERVOIR_WARNINGS = (
    "Posição do reservatório como publicada no cadastro do ONS; não é a topografia nem o "
    "contorno do lago.",
    "A cor mostra a energia armazenada (EAR) do dia; valores acima de 100% ocorrem quando o "
    "reservatório está vertendo, e abaixo de 0% abaixo do volume mínimo operativo.",
)


@router.get("/reservoirs", response_model=ReservoirCollection)
def geo_reservoirs(
    session: SessionDep,
    cache: PublicCacheDep,
    day: Annotated[date | None, Query(alias="date", examples=["2026-09-30"])] = None,
    subsystem: Annotated[Literal["N", "NE", "S", "SE"] | None, Query()] = None,
) -> ReservoirCollection:
    """Reservoirs with a position and the storage of one day (default the latest with data)."""

    def load() -> ReservoirCollection:
        latest = session.scalar(select(func.max(ReservoirDaily.day)))
        chosen = day or latest
        if (
            day is not None
            and session.scalar(
                select(func.count()).select_from(ReservoirDaily).where(ReservoirDaily.day == day)
            )
            == 0
        ):
            raise HTTPException(status_code=404, detail="No data for this day.")
        stmt = select(Reservoir, ReservoirDaily).outerjoin(
            ReservoirDaily,
            (ReservoirDaily.reservoir_id == Reservoir.id) & (ReservoirDaily.day == chosen),
        )
        if subsystem is not None:
            stmt = stmt.where(Reservoir.subsystem == subsystem)
        features: list[ReservoirFeature] = []
        total = 0
        for reservoir, daily in session.execute(stmt.order_by(Reservoir.name)).all():
            total += 1
            if reservoir.latitude is None or reservoir.longitude is None:
                continue
            features.append(
                ReservoirFeature(
                    geometry=GeoPoint(
                        coordinates=(float(reservoir.longitude), float(reservoir.latitude))
                    ),
                    properties=ReservoirProperties(
                        slug=reservoir.slug,
                        name=reservoir.name,
                        plant_name=reservoir.plant_name,
                        subsystem=reservoir.subsystem,
                        basin=reservoir.basin,
                        river=reservoir.river,
                        useful_volume_hm3=_num(reservoir.useful_volume_hm3),
                        storage_pct=_num(daily.storage_pct) if daily else None,
                        ena_storable_pct_mlt=_num(daily.ena_storable_pct_mlt) if daily else None,
                        day=daily.day if daily else None,
                    ),
                )
            )
        return ReservoirCollection(
            meta=GeoMeta(
                source_name="Operador Nacional do Sistema Elétrico (ONS), dados abertos",
                source_url="https://dados.ons.org.br/",
                license=ONS_LICENSE,
                as_of=chosen,
                updated_at=None,
                warnings=list(RESERVOIR_WARNINGS),
                total=total,
                omitted=total - len(features),
            ),
            features=features,
        )

    return cache.get_or_set(load)


def _num(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


VoltageMin = Annotated[
    float | None,
    Query(ge=0, le=1000, description="Only equipment of at least this voltage (kV)."),
]
StateFilter = Annotated[str | None, Query(pattern=r"^[A-Za-z]{2}$")]

GRID_COORDINATE_WARNING = (
    "Posição das subestações como publicada pelo ONS; não é topografia nem levantamento."
)
LINES_WARNINGS = (
    "Esquemático: cada linha é um segmento reto entre as duas subestações, não o traçado real "
    "da linha.",
    GRID_COORDINATE_WARNING,
)


def _grid_meta(warnings: tuple[str, ...], total: int, shown: int) -> GeoMeta:
    return GeoMeta(
        source_name="Operador Nacional do Sistema Elétrico (ONS), dados abertos",
        source_url="https://dados.ons.org.br/",
        license=ONS_LICENSE,
        as_of=None,
        updated_at=None,
        warnings=list(warnings),
        total=total,
        omitted=total - shown,
    )


@router.get("/substations", response_model=SubstationCollection)
def geo_substations(
    session: SessionDep,
    cache: PublicCacheDep,
    voltage_min: VoltageMin = None,
    state: StateFilter = None,
) -> SubstationCollection:
    """Current substations that have a position (one point per voltage level)."""

    def load() -> SubstationCollection:
        stmt = select(Substation).where(Substation.valid_to.is_(None))
        if voltage_min is not None:
            stmt = stmt.where(Substation.voltage_kv >= voltage_min)
        if state is not None:
            stmt = stmt.where(Substation.state == state.upper())
        rows = session.scalars(stmt.order_by(Substation.voltage_kv.desc(), Substation.name)).all()
        features = [
            SubstationFeature(
                geometry=GeoPoint(coordinates=(float(r.longitude), float(r.latitude))),
                properties=SubstationProperties(
                    station_id=r.station_id,
                    substation_id=r.substation_id,
                    name=r.name,
                    voltage_kv=_num(r.voltage_kv),
                    subsystem=r.subsystem,
                    state=r.state,
                    main_agent=r.main_agent,
                ),
            )
            for r in rows
            if r.latitude is not None and r.longitude is not None
        ]
        return SubstationCollection(
            meta=_grid_meta((GRID_COORDINATE_WARNING,), len(rows), len(features)),
            features=features,
        )

    return cache.get_or_set(load)


@router.get("/lines", response_model=LineCollection)
def geo_lines(
    session: SessionDep,
    cache: PublicCacheDep,
    voltage_min: VoltageMin = None,
    state: StateFilter = None,
) -> LineCollection:
    """Current transmission lines drawn as straight segments between their two substations."""

    def load() -> LineCollection:
        positions: dict[tuple[str, str | None], set[tuple[float, float]]] = {}
        by_name: dict[str, set[tuple[float, float]]] = {}
        for sub in session.scalars(
            select(Substation).where(
                Substation.valid_to.is_(None),
                Substation.latitude.is_not(None),
                Substation.longitude.is_not(None),
            )
        ):
            if sub.name is None or sub.latitude is None or sub.longitude is None:
                continue
            point = (float(sub.longitude), float(sub.latitude))
            positions.setdefault((sub.name, sub.state), set()).add(point)
            by_name.setdefault(sub.name, set()).add(point)

        def locate(name: str | None, end_state: str | None) -> tuple[float, float] | None:
            """The one position of the substation; no guess when two places share the name."""
            if name is None:
                return None
            options = positions.get((name, end_state)) if end_state else None
            if options is None:
                options = by_name.get(name, set())
            return next(iter(options)) if len(options) == 1 else None

        stmt = select(TransmissionLine).where(TransmissionLine.valid_to.is_(None))
        if voltage_min is not None:
            stmt = stmt.where(TransmissionLine.voltage_kv >= voltage_min)
        if state is not None:
            up = state.upper()
            stmt = stmt.where(
                or_(TransmissionLine.from_state == up, TransmissionLine.to_state == up)
            )
        rows = session.scalars(
            stmt.order_by(TransmissionLine.voltage_kv.desc(), TransmissionLine.equipment_code)
        ).all()
        features: list[LineFeature] = []
        for r in rows:
            start = locate(r.from_substation, r.from_state)
            end = locate(r.to_substation, r.to_state)
            if start is None or end is None or start == end:
                continue
            features.append(
                LineFeature(
                    geometry=GeoLine(coordinates=[start, end]),
                    properties=LineProperties(
                        equipment_code=r.equipment_code,
                        name=r.name,
                        voltage_kv=_num(r.voltage_kv),
                        length_km=_num(r.length_km),
                        from_substation=r.from_substation,
                        to_substation=r.to_substation,
                        from_state=r.from_state,
                        to_state=r.to_state,
                    ),
                )
            )
        return LineCollection(
            meta=_grid_meta(LINES_WARNINGS, len(rows), len(features)), features=features
        )

    return cache.get_or_set(load)


PLANT_WARNINGS = (
    "Posição aproximada pela subestação de conexão (casada pelo nome e pela UF), não o ponto da "
    "usina: várias usinas da mesma subestação aparecem no mesmo lugar.",
    "Usinas sem subestação identificada não têm posição e ficam fora do mapa; estão na lista "
    "'sem localização'.",
)


@router.get("/plants", response_model=PlantGeoCollection)
def geo_plants(
    session: SessionDep,
    cache: PublicCacheDep,
    month: MonthQuery = None,
    source: Annotated[Literal["wind", "solar"] | None, Query()] = None,
    state: StateFilter = None,
    slug: Annotated[str | None, Query(max_length=120, description="One plant, by slug.")] = None,
) -> PlantGeoCollection:
    """Wind and solar plants with a position, and their curtailment in one month."""
    up = state.upper() if state else None
    if up is not None and up not in STATES:
        raise HTTPException(status_code=404, detail="State not found.")

    def load() -> PlantGeoCollection:
        chosen = parse_month(month) if month is not None else latest_plant_month(session)
        stmt = (
            select(Plant, PlantLocation, PlantMonthlyCurtailment)
            .outerjoin(PlantLocation, PlantLocation.plant_id == Plant.id)
            .outerjoin(
                PlantMonthlyCurtailment,
                (PlantMonthlyCurtailment.plant_id == Plant.id)
                & (PlantMonthlyCurtailment.month == chosen),
            )
            .where(Plant.kind == "plant")
            .order_by(Plant.name)
        )
        if source is not None:
            stmt = stmt.where(Plant.source == source)
        if up is not None:
            stmt = stmt.where(Plant.state == up)
        if slug is not None:
            stmt = stmt.where(Plant.slug == slug)
        features: list[PlantGeoFeature] = []
        unlocated: list[UnlocatedPlant] = []
        total = 0
        for plant, location, metrics in session.execute(stmt).all():
            total += 1
            if location is None:
                unlocated.append(
                    UnlocatedPlant(
                        id=plant.id,
                        slug=plant.slug,
                        name=plant.name,
                        source=plant.source,
                        state=plant.state,
                        capacity_mw=_num(plant.capacity_mw),
                        connection_point=plant.connection_point,
                        curtailed_mwh=_num(metrics.curtailed_mwh) if metrics else None,
                    )
                )
                continue
            features.append(
                PlantGeoFeature(
                    geometry=GeoPoint(
                        coordinates=(float(location.longitude), float(location.latitude))
                    ),
                    properties=PlantGeoProperties(
                        id=plant.id,
                        slug=plant.slug,
                        name=plant.name,
                        source=plant.source,
                        state=plant.state,
                        subsystem=plant.subsystem,
                        capacity_mw=_num(plant.capacity_mw),
                        connection_point=plant.connection_point,
                        location_precision=location.location_precision,
                        matched_on=location.matched_on,
                        month=chosen if metrics else None,
                        curtailed_mwh=_num(metrics.curtailed_mwh) if metrics else None,
                        curtailment_pct=_num(metrics.curtailment_pct) if metrics else None,
                        estimated_loss_brl=_num(metrics.estimated_loss_brl) if metrics else None,
                    ),
                )
            )
        return PlantGeoCollection(
            meta=GeoMeta(
                source_name="Operador Nacional do Sistema Elétrico (ONS), dados abertos",
                source_url="https://dados.ons.org.br/",
                license=ONS_LICENSE,
                as_of=chosen,
                updated_at=None,
                warnings=list(PLANT_WARNINGS),
                total=total,
                omitted=len(unlocated),
            ),
            features=features,
            unlocated=unlocated,
        )

    return cache.get_or_set(load)
