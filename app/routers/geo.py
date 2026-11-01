"""Map layers: values per place, without geometry (the web draws the outlines itself)."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from app.cache import PublicCacheDep
from app.db import SessionDep
from app.geo_schemas import (
    GeoMeta,
    GeoPoint,
    ReservoirCollection,
    ReservoirFeature,
    ReservoirProperties,
)
from app.models import Reservoir, ReservoirDaily, StateMonthlyCurtailment
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
