import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CHAR,
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    MetaData,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    extract,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

BigIntId = BigInteger().with_variant(Integer(), "sqlite")


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def _now_default() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Plant(Base):
    __tablename__ = "plant"
    __table_args__ = (
        CheckConstraint("kind IN ('plant', 'cluster')", name="kind"),
        CheckConstraint("source IN ('wind', 'solar')", name="source"),
        CheckConstraint("subsystem IN ('N', 'NE', 'S', 'SE')", name="subsystem"),
        CheckConstraint("length(state) = 2 AND state = upper(state)", name="state"),
        Index("ix_plant_state_source", "state", "source"),
        Index("ix_plant_cluster_id", "cluster_id"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(CHAR(2), nullable=False)
    subsystem: Mapped[str] = mapped_column(String(3), nullable=False)
    cluster_id: Mapped[str | None] = mapped_column(Text, ForeignKey("plant.id"), nullable=True)
    ceg: Mapped[str | None] = mapped_column(Text)
    capacity_mw: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    connection_point: Mapped[str | None] = mapped_column(Text)
    operator: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = _now_default()


Index("ix_plant_name_lower", func.lower(Plant.name))


class PlantLocation(Base):
    """Where a plant is drawn on the map and how good that position is.

    ``substation``: the coordinate of the substation the plant connects to (matched on name and
    state; never on the name alone), so it is approximate. ``official``: a point published by the
    regulator, reserved for later. Written by the data pipeline, read by the API.
    """

    __tablename__ = "plant_location"
    __table_args__ = (
        CheckConstraint(
            "location_precision IN ('substation', 'official')", name="location_precision"
        ),
        CheckConstraint(
            "latitude BETWEEN -34 AND 6 AND longitude BETWEEN -74 AND -34", name="inside_brazil"
        ),
    )

    plant_id: Mapped[str] = mapped_column(
        Text, ForeignKey("plant.id", ondelete="CASCADE"), primary_key=True
    )
    latitude: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    longitude: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    location_precision: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    matched_on: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = _now_default()


class PlantMonthlyCurtailment(Base):
    __tablename__ = "plant_monthly_curtailment"
    __table_args__ = (
        CheckConstraint(
            "price_basis IS NULL OR price_basis IN ('PLD', 'CMO', 'PLD_FILLED', 'CMO_FILLED')",
            name="price_basis",
        ),
        Index("ix_plant_monthly_curtailment_month_national_rank", "month", "national_rank"),
        Index("ix_plant_monthly_curtailment_month_state_rank", "month", "state_rank"),
    )

    plant_id: Mapped[str] = mapped_column(Text, ForeignKey("plant.id"), primary_key=True)
    month: Mapped[date] = mapped_column(Date, primary_key=True)
    verified_generation_mwh: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    curtailed_mwh: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    curtailment_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    curtailed_rel_mwh: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    curtailed_cnf_mwh: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    curtailed_ene_mwh: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    curtailed_other_mwh: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    estimated_loss_brl: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    price_basis: Mapped[str | None] = mapped_column(Text)
    restricted_hours: Mapped[Decimal] = mapped_column(Numeric(7, 1), nullable=False)
    state_avg_curtailment_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    national_rank: Mapped[int | None] = mapped_column(Integer)
    state_rank: Mapped[int | None] = mapped_column(Integer)
    updated_at: Mapped[datetime] = _now_default()


class _CurtailmentAggregate:
    source: Mapped[str] = mapped_column(Text, primary_key=True)
    month: Mapped[date] = mapped_column(Date, primary_key=True)
    verified_generation_mwh: Mapped[Decimal] = mapped_column(Numeric(16, 3), nullable=False)
    curtailed_mwh: Mapped[Decimal] = mapped_column(Numeric(16, 3), nullable=False)
    curtailment_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    curtailed_rel_mwh: Mapped[Decimal] = mapped_column(Numeric(16, 3), nullable=False)
    curtailed_cnf_mwh: Mapped[Decimal] = mapped_column(Numeric(16, 3), nullable=False)
    curtailed_ene_mwh: Mapped[Decimal] = mapped_column(Numeric(16, 3), nullable=False)
    curtailed_other_mwh: Mapped[Decimal] = mapped_column(Numeric(16, 3), nullable=False)
    estimated_loss_brl: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    affected_plants: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = _now_default()


class StateMonthlyCurtailment(_CurtailmentAggregate, Base):
    __tablename__ = "state_monthly_curtailment"
    __table_args__ = (
        CheckConstraint("source IN ('wind', 'solar', 'total')", name="source"),
        CheckConstraint("length(state) = 2 AND state = upper(state)", name="state"),
    )

    state: Mapped[str] = mapped_column(CHAR(2), primary_key=True)


class SubsystemMonthlyCurtailment(_CurtailmentAggregate, Base):
    __tablename__ = "subsystem_monthly_curtailment"
    __table_args__ = (
        CheckConstraint("source IN ('wind', 'solar', 'total')", name="source"),
        CheckConstraint("subsystem IN ('N', 'NE', 'S', 'SE', 'SIN')", name="subsystem"),
    )

    subsystem: Mapped[str] = mapped_column(String(3), primary_key=True)


class LoadRun(Base):
    __tablename__ = "load_run"
    __table_args__ = (CheckConstraint("status IN ('running', 'success', 'failed')", name="status"),)

    id: Mapped[int] = mapped_column(BigIntId, Identity(), primary_key=True)
    dataset: Mapped[str] = mapped_column(Text, nullable=False)
    period: Mapped[date | None] = mapped_column(Date)
    source_file: Mapped[str | None] = mapped_column(Text)
    checksum: Mapped[str | None] = mapped_column(Text)
    row_count: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)


Index("ix_load_run_started_at", LoadRun.started_at.desc())


class MonthlyReport(Base):
    __tablename__ = "monthly_report"

    id: Mapped[int] = mapped_column(BigIntId, Identity(), primary_key=True)
    month: Mapped[date] = mapped_column(Date, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    summary: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now_default()
    updated_at: Mapped[datetime] = _now_default()


class EmailDispatch(Base):
    """One monthly send of a kind of e-mail ("report", "analysis"). At most one per kind and
    month, so pressing the button twice does not mail everyone twice."""

    __tablename__ = "email_dispatch"
    __table_args__ = (
        UniqueConstraint("kind", "month"),
        CheckConstraint("kind IN ('report', 'analysis')", name="kind"),
        CheckConstraint("status IN ('running', 'done', 'partial')", name="status"),
    )

    id: Mapped[int] = mapped_column(BigIntId, Identity(), primary_key=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    month: Mapped[date] = mapped_column(Date, nullable=False)
    report_id: Mapped[int | None] = mapped_column(BigIntId, ForeignKey("monthly_report.id"))
    status: Mapped[str] = mapped_column(Text, nullable=False, default="running")
    recipients: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime] = _now_default()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NewsletterSubscriber(Base):
    __tablename__ = "newsletter_subscriber"
    __table_args__ = (
        CheckConstraint("email = lower(email)", name="email_lowercase"),
        Index("ix_newsletter_subscriber_confirmation_token_hash", "confirmation_token_hash"),
        Index("ix_newsletter_subscriber_unsubscribe_token_hash", "unsubscribe_token_hash"),
    )

    id: Mapped[int] = mapped_column(BigIntId, Identity(), primary_key=True)
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    consented_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    unsubscribed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmation_token_hash: Mapped[str | None] = mapped_column(Text)
    confirmation_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    unsubscribe_token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    signup_source: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now_default()


class Organization(Base):
    __tablename__ = "organization"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _now_default()


class AppUser(Base):
    __tablename__ = "app_user"
    __table_args__ = (CheckConstraint("role IN ('owner', 'member', 'admin')", name="role"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    cognito_sub: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str | None] = mapped_column(Text)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("organization.id"), nullable=True
    )
    role: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _now_default()


JsonDocument = JSON().with_variant(JSONB(), "postgresql")


class UsageEvent(Base):
    __tablename__ = "usage_event"

    id: Mapped[int] = mapped_column(BigIntId, Identity(), primary_key=True)
    occurred_at: Mapped[datetime] = _now_default()
    category: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    section: Mapped[str | None] = mapped_column(Text)
    entity_type: Mapped[str | None] = mapped_column(Text)
    entity_id: Mapped[str | None] = mapped_column(Text)
    path: Mapped[str | None] = mapped_column(Text)
    properties: Mapped[dict[str, Any]] = mapped_column(JsonDocument, nullable=False, default=dict)
    member_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("member.id", ondelete="SET NULL"), nullable=True
    )
    member_role: Mapped[str | None] = mapped_column(Text)
    member_segment: Mapped[str | None] = mapped_column(Text)
    visitor_id: Mapped[str | None] = mapped_column(Text)
    session_key: Mapped[str | None] = mapped_column(Text)
    ip_hash: Mapped[str | None] = mapped_column(Text)
    user_agent: Mapped[str | None] = mapped_column(Text)
    device: Mapped[str | None] = mapped_column(Text)
    is_bot: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    referrer: Mapped[str | None] = mapped_column(Text)
    request_id: Mapped[str | None] = mapped_column(Text)


Index("ix_usage_event_occurred_at", UsageEvent.occurred_at)
Index("ix_usage_event_member_id_occurred_at", UsageEvent.member_id, UsageEvent.occurred_at)
Index(
    "ix_usage_event_category_action_occurred_at",
    UsageEvent.category,
    UsageEvent.action,
    UsageEvent.occurred_at,
)
Index("ix_usage_event_section_occurred_at", UsageEvent.section, UsageEvent.occurred_at)
Index("ix_usage_event_entity", UsageEvent.entity_type, UsageEvent.entity_id)


class HourlyCurtailment(Base):
    __tablename__ = "hourly_curtailment"
    __table_args__ = (
        CheckConstraint("hour BETWEEN 0 AND 23", name="hour"),
        CheckConstraint("day_type IN ('weekday', 'weekend')", name="day_type"),
        CheckConstraint("source IN ('wind', 'solar', 'total')", name="source"),
        CheckConstraint("subsystem IN ('N', 'NE', 'S', 'SE', 'SIN')", name="subsystem"),
    )

    subsystem: Mapped[str] = mapped_column(String(3), primary_key=True)
    source: Mapped[str] = mapped_column(Text, primary_key=True)
    month: Mapped[date] = mapped_column(Date, primary_key=True)
    day_type: Mapped[str] = mapped_column(Text, primary_key=True)
    hour: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    curtailed_mwh: Mapped[Decimal] = mapped_column(Numeric(16, 3), nullable=False)
    generation_mwh: Mapped[Decimal] = mapped_column(Numeric(16, 3), nullable=False)
    days: Mapped[int] = mapped_column(Integer, nullable=False)


GENERATION_SOURCES = "('hydro', 'thermal', 'wind', 'solar')"


class SubsystemHourlyBalance(Base):
    """Hourly energy balance per subsystem (ONS balanco_energia_subsistema_ho), in average MW."""

    __tablename__ = "subsystem_hourly_balance"
    __table_args__ = (
        CheckConstraint("subsystem IN ('N', 'NE', 'S', 'SE')", name="subsystem"),
        Index("ix_subsystem_hourly_balance_hour", "hour"),
    )

    hour: Mapped[datetime] = mapped_column(DateTime, primary_key=True)  # Brasilia time
    subsystem: Mapped[str] = mapped_column(String(3), primary_key=True)
    hour_utc: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    hydro_mw_avg: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    thermal_mw_avg: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    wind_mw_avg: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    solar_mw_avg: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    load_mw_avg: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    net_interchange_mw_avg: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))


class SubsystemMonthlyGeneration(Base):
    __tablename__ = "subsystem_monthly_generation"
    __table_args__ = (
        CheckConstraint(f"source IN {GENERATION_SOURCES}", name="source"),
        CheckConstraint("subsystem IN ('N', 'NE', 'S', 'SE', 'SIN')", name="subsystem"),
    )

    month: Mapped[date] = mapped_column(Date, primary_key=True)
    subsystem: Mapped[str] = mapped_column(String(3), primary_key=True)
    source: Mapped[str] = mapped_column(Text, primary_key=True)
    energy_mwh: Mapped[Decimal] = mapped_column(Numeric(16, 3), nullable=False)
    avg_mw: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    peak_mw: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    share_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))


class PowerPlant(Base):
    """Every plant of the generation fleet (hydro, thermal, nuclear, wind, solar).

    ``plant`` only holds the wind and solar plants of the curtailment product, so the fleet lives
    in its own table. Wind and solar plants keep the same id and slug rule as in ``plant``.
    """

    __tablename__ = "power_plant"
    __table_args__ = (
        CheckConstraint(
            "source_type IN ('hydro', 'thermal', 'nuclear', 'wind', 'solar', 'other')",
            name="source_type",
        ),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    fuel_type: Mapped[str | None] = mapped_column(Text)
    state: Mapped[str | None] = mapped_column(CHAR(2))
    subsystem: Mapped[str | None] = mapped_column(String(3))
    ceg: Mapped[str | None] = mapped_column(Text)
    capacity_mw: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    updated_at: Mapped[datetime] = _now_default()


class PlantMonthlyGeneration(Base):
    __tablename__ = "plant_monthly_generation"
    __table_args__ = (
        CheckConstraint(
            "capacity_factor IS NULL OR capacity_factor BETWEEN 0 AND 1.05", name="capacity_factor"
        ),
    )

    month: Mapped[date] = mapped_column(Date, primary_key=True)
    plant_id: Mapped[str] = mapped_column(Text, ForeignKey("power_plant.id"), primary_key=True)
    energy_mwh: Mapped[Decimal] = mapped_column(Numeric(16, 3), nullable=False)
    avg_mw: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    peak_mw: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    capacity_factor: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))


class InterchangeHourly(Base):
    """Hourly interchange between two areas, in average MW; positive means origin -> destination.

    National rows go between subsystems; international rows go from ``BR`` to a country.
    """

    __tablename__ = "interchange_hourly"
    __table_args__ = (
        CheckConstraint("scope IN ('national', 'international')", name="scope"),
        Index("ix_interchange_hourly_hour", "hour"),
    )

    hour: Mapped[datetime] = mapped_column(DateTime, primary_key=True)  # Brasilia time
    origin: Mapped[str] = mapped_column(Text, primary_key=True)
    destination: Mapped[str] = mapped_column(Text, primary_key=True)
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    hour_utc: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    flow_mw_avg: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    scheduled_mw_avg: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))


class InterchangeMonthly(Base):
    __tablename__ = "interchange_monthly"
    __table_args__ = (CheckConstraint("scope IN ('national', 'international')", name="scope"),)

    month: Mapped[date] = mapped_column(Date, primary_key=True)
    origin: Mapped[str] = mapped_column(Text, primary_key=True)
    destination: Mapped[str] = mapped_column(Text, primary_key=True)
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    energy_mwh: Mapped[Decimal] = mapped_column(Numeric(16, 3), nullable=False)
    scheduled_energy_mwh: Mapped[Decimal | None] = mapped_column(Numeric(16, 3))
    avg_mw: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    peak_mw: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    min_mw: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)


class ThermalDispatchMonthly(Base):
    """Verified and programmed thermal generation per plant and dispatch reason.

    The reasons of the ONS file overlap in places (``merit_order`` contains
    ``merit_order_above_inflexibility`` and ``inflexibility`` contains its two parts), so rows of
    different reasons must not be added up; ``total`` is the plant's whole generation.
    """

    __tablename__ = "thermal_dispatch_monthly"
    __table_args__ = (Index("ix_thermal_dispatch_monthly_reason", "reason", "month"),)

    month: Mapped[date] = mapped_column(Date, primary_key=True)
    plant_code: Mapped[str] = mapped_column(Text, primary_key=True)  # cod_usinaplanejamento
    reason: Mapped[str] = mapped_column(Text, primary_key=True)
    plant_name: Mapped[str] = mapped_column(Text, nullable=False)
    ceg: Mapped[str | None] = mapped_column(Text)
    fuel_type: Mapped[str | None] = mapped_column(Text)
    subsystem: Mapped[str] = mapped_column(String(3), nullable=False)
    verified_mwh: Mapped[Decimal] = mapped_column(Numeric(16, 3), nullable=False)
    programmed_mwh: Mapped[Decimal | None] = mapped_column(Numeric(16, 3))


class Reservoir(Base):
    """Reservoir register (ONS ``reservatorio``); ``id`` is the ONS res_id."""

    __tablename__ = "reservoir"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    reservoir_type: Mapped[str | None] = mapped_column(Text)
    planning_code: Mapped[int | None] = mapped_column(Integer)
    station_code: Mapped[int | None] = mapped_column(Integer)
    plant_name: Mapped[str | None] = mapped_column(Text)
    ceg: Mapped[str | None] = mapped_column(Text)
    subsystem: Mapped[str | None] = mapped_column(String(3))
    ree: Mapped[str | None] = mapped_column(Text)
    basin: Mapped[str | None] = mapped_column(Text)
    river: Mapped[str | None] = mapped_column(Text)
    commissioned_on: Mapped[date | None] = mapped_column(Date)
    max_level_m: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    min_level_m: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    max_volume_hm3: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    min_volume_hm3: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    useful_volume_hm3: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    updated_at: Mapped[datetime] = _now_default()


class SubsystemStorageDaily(Base):
    """Daily stored energy (EAR, MW-month) and natural inflow energy (ENA, average MW)."""

    __tablename__ = "subsystem_storage_daily"
    __table_args__ = (
        CheckConstraint("subsystem IN ('N', 'NE', 'S', 'SE')", name="subsystem"),
        CheckConstraint("storage_pct IS NULL OR storage_pct BETWEEN 0 AND 200", name="storage_pct"),
    )

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    subsystem: Mapped[str] = mapped_column(String(3), primary_key=True)
    storage_max_mw_month: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    storage_mw_month: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    storage_pct: Mapped[Decimal | None] = mapped_column(Numeric(7, 4))
    ena_gross_mw_avg: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    ena_gross_pct_mlt: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    ena_storable_mw_avg: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    ena_storable_pct_mlt: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))


class ReservoirDaily(Base):
    __tablename__ = "reservoir_daily"
    __table_args__ = (
        # no range check on storage_pct: it is negative below the minimum operating volume and
        # above 100 while a reservoir spills (the ONS shows -83% to 379%)
        Index("ix_reservoir_daily_reservoir_id_day", "reservoir_id", "day"),
    )

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    reservoir_id: Mapped[str] = mapped_column(Text, ForeignKey("reservoir.id"), primary_key=True)
    storage_mw_month: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    storage_max_mw_month: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    storage_pct: Mapped[Decimal | None] = mapped_column(Numeric(7, 4))
    useful_volume_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 3))
    ena_gross_mw_avg: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    ena_gross_pct_mlt: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    ena_storable_mw_avg: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    ena_storable_pct_mlt: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    inflow_m3s: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    natural_inflow_m3s: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    outflow_m3s: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    turbined_m3s: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    spilled_m3s: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    upstream_level_m: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    downstream_level_m: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))


class PlantMonthlySpilledEnergy(Base):
    """Energy that was spilled although it could have been turbined (ONS energia vertida)."""

    __tablename__ = "plant_monthly_spilled_energy"

    month: Mapped[date] = mapped_column(Date, primary_key=True)
    plant_code: Mapped[str] = mapped_column(Text, primary_key=True)  # cod_usina (optimisation code)
    plant_name: Mapped[str] = mapped_column(Text, nullable=False)
    subsystem: Mapped[str | None] = mapped_column(String(3))
    basin: Mapped[str | None] = mapped_column(Text)
    river: Mapped[str | None] = mapped_column(Text)
    agent: Mapped[str | None] = mapped_column(Text)
    spilled_energy_mwh: Mapped[Decimal] = mapped_column(Numeric(16, 3), nullable=False)
    spilled_turbinable_energy_mwh: Mapped[Decimal] = mapped_column(Numeric(16, 3), nullable=False)


class TransmissionLine(Base):
    """A transmission line of the ONS grid register, versioned by snapshot.

    A new row is written when an attribute changes: ``valid_from`` is the snapshot date that first
    showed this version and ``valid_to`` the snapshot date that no longer did (NULL = current).
    """

    __tablename__ = "transmission_line"
    __table_args__ = (
        Index(
            "uq_transmission_line_current",
            "equipment_code",
            unique=True,
            postgresql_where=text("valid_to IS NULL"),
            sqlite_where=text("valid_to IS NULL"),
        ),
        Index("ix_transmission_line_voltage_kv", "voltage_kv"),
    )

    equipment_code: Mapped[str] = mapped_column(Text, primary_key=True)
    valid_from: Mapped[date] = mapped_column(Date, primary_key=True)
    valid_to: Mapped[date | None] = mapped_column(Date)
    row_hash: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str | None] = mapped_column(Text)
    voltage_kv: Mapped[Decimal | None] = mapped_column(Numeric(7, 2))
    line_type: Mapped[str | None] = mapped_column(Text)
    network_type: Mapped[str | None] = mapped_column(Text)
    owner_agent: Mapped[str | None] = mapped_column(Text)
    from_substation: Mapped[str | None] = mapped_column(Text)
    to_substation: Mapped[str | None] = mapped_column(Text)
    from_subsystem: Mapped[str | None] = mapped_column(String(3))
    to_subsystem: Mapped[str | None] = mapped_column(String(3))
    from_state: Mapped[str | None] = mapped_column(String(3))
    to_state: Mapped[str | None] = mapped_column(String(3))
    length_km: Mapped[Decimal | None] = mapped_column(Numeric(9, 3))
    positive_seq_resistance: Mapped[Decimal | None] = mapped_column(Numeric(16, 6))
    positive_seq_reactance: Mapped[Decimal | None] = mapped_column(Numeric(16, 6))
    positive_seq_shunt: Mapped[Decimal | None] = mapped_column(Numeric(16, 6))
    capacity_long_no_limit_a: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    capacity_long_with_limit_a: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    capacity_short_no_limit_a: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    capacity_short_with_limit_a: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    commissioned_on: Mapped[date | None] = mapped_column(Date)
    decommissioned_on: Mapped[date | None] = mapped_column(Date)
    planned_on: Mapped[date | None] = mapped_column(Date)
    from_bus: Mapped[int | None] = mapped_column(Integer)
    to_bus: Mapped[int | None] = mapped_column(Integer)


class Substation(Base):
    """A substation station (one voltage level of a substation), versioned like the lines."""

    __tablename__ = "substation"
    __table_args__ = (
        Index(
            "uq_substation_current",
            "station_id",
            unique=True,
            postgresql_where=text("valid_to IS NULL"),
            sqlite_where=text("valid_to IS NULL"),
        ),
        Index("ix_substation_state", "state"),
    )

    station_id: Mapped[str] = mapped_column(Text, primary_key=True)
    valid_from: Mapped[date] = mapped_column(Date, primary_key=True)
    valid_to: Mapped[date | None] = mapped_column(Date)
    row_hash: Mapped[str] = mapped_column(Text, nullable=False)
    substation_id: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str | None] = mapped_column(Text)
    voltage_kv: Mapped[Decimal | None] = mapped_column(Numeric(7, 2))
    subsystem: Mapped[str | None] = mapped_column(String(3))
    state: Mapped[str | None] = mapped_column(String(3))
    main_agent: Mapped[str | None] = mapped_column(Text)
    bus_number: Mapped[int | None] = mapped_column(Integer)
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))  # as published by the ONS
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))


class TransformerCapacity(Base):
    __tablename__ = "transformer_capacity"
    __table_args__ = (
        Index(
            "uq_transformer_capacity_current",
            "equipment_code",
            unique=True,
            postgresql_where=text("valid_to IS NULL"),
            sqlite_where=text("valid_to IS NULL"),
        ),
    )

    equipment_code: Mapped[str] = mapped_column(Text, primary_key=True)
    valid_from: Mapped[date] = mapped_column(Date, primary_key=True)
    valid_to: Mapped[date | None] = mapped_column(Date)
    row_hash: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str | None] = mapped_column(Text)
    transformer_type: Mapped[str | None] = mapped_column(Text)
    substation: Mapped[str | None] = mapped_column(Text)
    owner_agent: Mapped[str | None] = mapped_column(Text)
    subsystem: Mapped[str | None] = mapped_column(String(3))
    state: Mapped[str | None] = mapped_column(String(3))
    primary_kv: Mapped[Decimal | None] = mapped_column(Numeric(7, 2))
    secondary_kv: Mapped[Decimal | None] = mapped_column(Numeric(7, 2))
    tertiary_kv: Mapped[Decimal | None] = mapped_column(Numeric(7, 2))
    rated_mva: Mapped[Decimal | None] = mapped_column(Numeric(9, 2))
    network_type: Mapped[str | None] = mapped_column(Text)
    commissioned_on: Mapped[date | None] = mapped_column(Date)
    decommissioned_on: Mapped[date | None] = mapped_column(Date)
    primary_bus: Mapped[int | None] = mapped_column(Integer)
    secondary_bus: Mapped[int | None] = mapped_column(Integer)


class Member(Base):
    __tablename__ = "member"
    __table_args__ = (
        CheckConstraint("email = lower(email)", name="email_lowercase"),
        Index("ix_member_lead_score", "lead_score"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    organization: Mapped[str | None] = mapped_column(Text)
    job_title: Mapped[str | None] = mapped_column(Text)
    segment: Mapped[str | None] = mapped_column(Text)
    company_size: Mapped[str | None] = mapped_column(Text)
    institution: Mapped[str | None] = mapped_column(Text)
    study_level: Mapped[str | None] = mapped_column(Text)
    regions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    plants: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    interests: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    phone: Mapped[str | None] = mapped_column(Text)
    referral: Mapped[str | None] = mapped_column(Text)
    signup_source: Mapped[str | None] = mapped_column(Text)
    marketing_opt_in: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    privacy_consent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lead_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lead_tier: Mapped[str] = mapped_column(Text, nullable=False, default="cold")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now_default()


class MemberToken(Base):
    __tablename__ = "member_token"
    __table_args__ = (CheckConstraint("kind IN ('verify', 'reset')", name="kind"),)

    id: Mapped[int] = mapped_column(BigIntId, Identity(), primary_key=True)
    member_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("member.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    created_at: Mapped[datetime] = _now_default()


class MemberSession(Base):
    __tablename__ = "member_session"

    id: Mapped[int] = mapped_column(BigIntId, Identity(), primary_key=True)
    member_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("member.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = _now_default()


Index("ix_member_token_member_id", MemberToken.member_id)
Index("ix_member_session_member_id", MemberSession.member_id)


class ForecastModel(Base):
    """Metadata and training results of a registered forecast model (written by the ML job)."""

    __tablename__ = "forecast_model"

    id: Mapped[int] = mapped_column(BigIntId, Identity(), primary_key=True)
    mlflow_run_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    model_version: Mapped[str] = mapped_column(Text, nullable=False)
    trained_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    data_period: Mapped[dict[str, Any]] = mapped_column(JsonDocument, nullable=False)
    n_series: Mapped[int] = mapped_column(Integer, nullable=False)
    n_rows: Mapped[int] = mapped_column(Integer, nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JsonDocument, nullable=False)
    calibration: Mapped[dict[str, Any]] = mapped_column(JsonDocument, nullable=False)
    feature_importance: Mapped[dict[str, Any]] = mapped_column(JsonDocument, nullable=False)
    model_card: Mapped[dict[str, Any]] = mapped_column(JsonDocument, nullable=False)
    is_current: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = _now_default()


Index(
    "uq_forecast_model_current",
    ForecastModel.is_current,
    unique=True,
    postgresql_where=ForecastModel.is_current,
    sqlite_where=ForecastModel.is_current,
)


class ForecastRun(Base):
    """One scoring batch. Readers only see runs in status ``ready`` (complete)."""

    __tablename__ = "forecast_run"

    id: Mapped[int] = mapped_column(BigIntId, Identity(), primary_key=True)
    model_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("forecast_model.id"), nullable=False
    )
    created_at: Mapped[datetime] = _now_default()
    origin_ts: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    data_through: Mapped[date] = mapped_column(Date, nullable=False)
    horizon_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        CheckConstraint("status IN ('loading', 'ready')", name="status"),
        UniqueConstraint("model_id", "origin_ts", name="uq_forecast_run_model_origin"),
    )


class ForecastHourly(Base):
    """Hourly risk per series. ``hour_ts`` is Brasilia local time (naive), like the lake."""

    __tablename__ = "forecast_hourly"

    run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("forecast_run.id", ondelete="CASCADE"), primary_key=True
    )
    source: Mapped[str] = mapped_column(Text, primary_key=True)
    scope: Mapped[str] = mapped_column(Text, primary_key=True)
    hour_ts: Mapped[datetime] = mapped_column(DateTime, primary_key=True)
    risk_probability: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    expected_curtailment_pct: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    applicable: Mapped[bool] = mapped_column(Boolean, nullable=False)

    __table_args__ = (
        CheckConstraint("source IN ('wind', 'solar')", name="source"),
        CheckConstraint("risk_probability BETWEEN 0 AND 1", name="risk_range"),
    )


FLAG_NAMES_SQL = "('Verde', 'Amarela', 'Vermelha P1', 'Vermelha P2', 'Escassez Hídrica')"
FORECAST_FLAGS_SQL = "('Verde', 'Amarela', 'Vermelha P1', 'Vermelha P2')"


class FlagRuleMonth(Base):
    """Inputs and bands of the tariff-flag rule for one month, as published by CCEE (InfoBandeira).

    Written by the pipeline (``energia_data``). Only numeric facts and the bulletin reference are
    stored, never the bulletin file itself.
    """

    __tablename__ = "flag_rule_month"
    __table_args__ = (
        CheckConstraint("pld_min_brl_per_mwh <= pld_max_brl_per_mwh", name="pld_range"),
        CheckConstraint(
            "green_upper_brl_per_mwh <= yellow_upper_brl_per_mwh "
            "AND yellow_upper_brl_per_mwh <= red1_upper_brl_per_mwh "
            "AND red1_upper_brl_per_mwh <= pld_max_brl_per_mwh",
            name="band_order",
        ),
        CheckConstraint(f"flag IN {FLAG_NAMES_SQL}", name="flag"),
    )

    month: Mapped[date] = mapped_column(Date, primary_key=True)
    rule_version: Mapped[str] = mapped_column(Text, nullable=False)
    pld_min_brl_per_mwh: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    pld_max_brl_per_mwh: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    gh_mwmed: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    gf_mwmed: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    gsf: Mapped[Decimal] = mapped_column(Numeric(4, 2), nullable=False)
    pld_trigger_brl_per_mwh: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    gfom_mwmed: Mapped[Decimal] = mapped_column(
        Numeric(12, 3), nullable=False, default=0, server_default=text("0")
    )
    green_upper_brl_per_mwh: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    yellow_upper_brl_per_mwh: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    red1_upper_brl_per_mwh: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    flag: Mapped[str] = mapped_column(Text, nullable=False)
    bulletin_number: Mapped[int | None] = mapped_column(Integer)
    bulletin_url: Mapped[str | None] = mapped_column(Text)
    bulletin_published_on: Mapped[date | None] = mapped_column(Date)
    revised_on: Mapped[date | None] = mapped_column(Date)
    updated_at: Mapped[datetime] = _now_default()


class FlagForecastRun(Base):
    """One forecast of a month's flag at a given lead. Readers only see ``status = 'ready'``."""

    __tablename__ = "flag_forecast_run"
    __table_args__ = (
        CheckConstraint("status IN ('loading', 'ready')", name="status"),
        CheckConstraint("lead_days > 0", name="lead_days"),
        UniqueConstraint("target_month", "lead_days", "generated_at", name="uq_flag_forecast_run"),
    )

    id: Mapped[int] = mapped_column(BigIntId, Identity(), primary_key=True)
    target_month: Mapped[date] = mapped_column(Date, nullable=False)
    lead_days: Mapped[int] = mapped_column(Integer, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    data_through: Mapped[date] = mapped_column(Date, nullable=False)
    model_version: Mapped[str] = mapped_column(Text, nullable=False)
    rule_version: Mapped[str] = mapped_column(Text, nullable=False)
    trigger_p10_brl_per_mwh: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    trigger_p50_brl_per_mwh: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    trigger_p90_brl_per_mwh: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    status: Mapped[str] = mapped_column(Text, nullable=False)


Index("ix_flag_forecast_run_target", FlagForecastRun.target_month, FlagForecastRun.lead_days)


class FlagForecastProb(Base):
    """Probability of each flag in a run, with the band of that flag used for the run."""

    __tablename__ = "flag_forecast_prob"
    __table_args__ = (
        CheckConstraint(f"flag IN {FORECAST_FLAGS_SQL}", name="flag"),
        CheckConstraint("prob BETWEEN 0 AND 1", name="prob_range"),
    )

    run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("flag_forecast_run.id", ondelete="CASCADE"), primary_key=True
    )
    flag: Mapped[str] = mapped_column(Text, primary_key=True)
    prob: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    band_lower_brl_per_mwh: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    band_upper_brl_per_mwh: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)


class FlagForecastInput(Base):
    """Key inputs of a run (values, dates, sources), kept as JSON for audit."""

    __tablename__ = "flag_forecast_input"

    run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("flag_forecast_run.id", ondelete="CASCADE"), primary_key=True
    )
    inputs: Mapped[dict[str, Any]] = mapped_column(JsonDocument, nullable=False)


class FlagForecastScore(Base):
    """Scoreboard row, written after the official flag is announced. Never rewritten."""

    __tablename__ = "flag_forecast_score"
    __table_args__ = (
        CheckConstraint(f"actual_flag IN {FORECAST_FLAGS_SQL}", name="actual_flag"),
        CheckConstraint("prob_actual BETWEEN 0 AND 1", name="prob_actual_range"),
        CheckConstraint("brier >= 0", name="brier"),
    )

    run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("flag_forecast_run.id", ondelete="CASCADE"), primary_key=True
    )
    actual_flag: Mapped[str] = mapped_column(Text, nullable=False)
    prob_actual: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    brier: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    top_hit: Mapped[bool] = mapped_column(Boolean, nullable=False)
    scored_at: Mapped[datetime] = _now_default()


for _name in (
    "plant_monthly_curtailment",
    "state_monthly_curtailment",
    "subsystem_monthly_curtailment",
    "hourly_curtailment",
    "monthly_report",
    "subsystem_monthly_generation",
    "plant_monthly_generation",
    "interchange_monthly",
    "thermal_dispatch_monthly",
    "plant_monthly_spilled_energy",
):
    _table = Base.metadata.tables[_name]
    _table.append_constraint(
        CheckConstraint(extract("day", _table.c.month) == 1, name="month_first_day")
    )


class NewsSource(Base):
    """A public source of sector news and the license it declares (seeded by migration)."""

    __tablename__ = "news_source"

    id: Mapped[int] = mapped_column(BigIntId, Identity(), primary_key=True)
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    publisher_name: Mapped[str] = mapped_column(Text, nullable=False)
    homepage_url: Mapped[str] = mapped_column(Text, nullable=False)
    feed_url: Mapped[str | None] = mapped_column(Text)
    fetch_method: Mapped[str] = mapped_column(Text, nullable=False)
    license_code: Mapped[str] = mapped_column(Text, nullable=False)
    license_url: Mapped[str] = mapped_column(Text, nullable=False)
    license_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    license_evidence_url: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )

    __table_args__ = (
        CheckConstraint(
            "fetch_method IN ('rss', 'api', 'listing', 'open-data')", name="fetch_method"
        ),
    )


class NewsItem(Base):
    """One news item exactly as the source published it.

    The pipeline writes everything except the admin columns (status, editor_*, related_links).
    """

    __tablename__ = "news_item"

    id: Mapped[int] = mapped_column(BigIntId, Identity(), primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("news_source.id"), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    topics: Mapped[list[str]] = mapped_column(JsonDocument, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default="published", server_default="published"
    )
    editor_note: Mapped[str | None] = mapped_column(Text)
    editor_note_by: Mapped[str | None] = mapped_column(Text)
    editor_note_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    related_links: Mapped[list[dict[str, Any]] | None] = mapped_column(JsonDocument)

    __table_args__ = (
        CheckConstraint("status IN ('published', 'hidden', 'removed_on_request')", name="status"),
        Index("ix_news_item_published_at", "published_at", "id"),
        Index("ix_news_item_source_id", "source_id"),
    )


class RegulatoryAct(Base):
    """An official act published in the DOU (no copyright, Lei 9.610/1998 art. 8, IV)."""

    __tablename__ = "regulatory_act"

    id: Mapped[int] = mapped_column(BigIntId, Identity(), primary_key=True)
    organ: Mapped[str] = mapped_column(Text, nullable=False)
    act_type: Mapped[str] = mapped_column(Text, nullable=False)
    act_number: Mapped[str | None] = mapped_column(Text)
    act_date: Mapped[date | None] = mapped_column(Date)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    body: Mapped[str | None] = mapped_column(Text)
    dou_date: Mapped[date] = mapped_column(Date, nullable=False)
    dou_section: Mapped[int | None] = mapped_column(SmallInteger)
    dou_edition: Mapped[str | None] = mapped_column(Text)
    dou_page: Mapped[str | None] = mapped_column(Text)
    dou_url: Mapped[str] = mapped_column(Text, nullable=False)
    topics: Mapped[list[str]] = mapped_column(JsonDocument, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default="published", server_default="published"
    )
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("status IN ('published', 'hidden', 'removed_on_request')", name="status"),
        UniqueConstraint("dou_url", "content_hash", name="uq_regulatory_act_dou_url_hash"),
        Index("ix_regulatory_act_dou_date", "dou_date", "id"),
    )


class DataSource(Base):
    """Where a dataset comes from: publisher, license and the attribution text shown on screen."""

    __tablename__ = "data_source"

    slug: Mapped[str] = mapped_column(Text, primary_key=True)
    publisher_name: Mapped[str] = mapped_column(Text)
    dataset_name: Mapped[str] = mapped_column(Text)
    dataset_url: Mapped[str] = mapped_column(Text)
    license_code: Mapped[str] = mapped_column(Text)
    license_url: Mapped[str] = mapped_column(Text)
    license_verified_at: Mapped[date] = mapped_column(Date)
    attribution_text: Mapped[str] = mapped_column(Text)
    update_frequency: Mapped[str] = mapped_column(Text)


class PldHourly(Base):
    """Hourly PLD per submarket: the official series or a "shadow" methodology (CCEE)."""

    __tablename__ = "pld_hourly"
    __table_args__ = (
        CheckConstraint("subsystem IN ('N', 'NE', 'S', 'SE')", name="subsystem"),
        CheckConstraint("variant IN ('official', 'shadow')", name="variant"),
        CheckConstraint("pld_brl_per_mwh >= 0", name="price"),
        Index("ix_pld_hourly_hour", "hour"),
    )

    hour_utc: Mapped[datetime] = mapped_column(DateTime, primary_key=True)
    hour: Mapped[datetime] = mapped_column(DateTime)
    subsystem: Mapped[str] = mapped_column(String(3), primary_key=True)
    variant: Mapped[str] = mapped_column(String(10), primary_key=True)
    method: Mapped[str] = mapped_column(Text, primary_key=True)
    pld_brl_per_mwh: Mapped[Decimal] = mapped_column(Numeric(12, 2))


class PldWeekly(Base):
    __tablename__ = "pld_weekly"
    __table_args__ = (CheckConstraint("subsystem IN ('N', 'NE', 'S', 'SE')", name="subsystem"),)

    week_start: Mapped[date] = mapped_column(Date, primary_key=True)
    subsystem: Mapped[str] = mapped_column(String(3), primary_key=True)
    pld_avg_brl_per_mwh: Mapped[Decimal] = mapped_column(Numeric(12, 2))


class PldDaily(Base):
    __tablename__ = "pld_daily"
    __table_args__ = (CheckConstraint("subsystem IN ('N', 'NE', 'S', 'SE')", name="subsystem"),)

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    subsystem: Mapped[str] = mapped_column(String(3), primary_key=True)
    pld_avg_brl_per_mwh: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    pld_min_brl_per_mwh: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    pld_max_brl_per_mwh: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    pld_std_brl_per_mwh: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    hours_at_floor: Mapped[int] = mapped_column(Integer)
    hours_at_cap: Mapped[int] = mapped_column(Integer)
    hours: Mapped[int] = mapped_column(Integer)


class PldMonthly(Base):
    __tablename__ = "pld_monthly"
    __table_args__ = (CheckConstraint("subsystem IN ('N', 'NE', 'S', 'SE')", name="subsystem"),)

    month: Mapped[date] = mapped_column(Date, primary_key=True)
    subsystem: Mapped[str] = mapped_column(String(3), primary_key=True)
    pld_avg_brl_per_mwh: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    pld_min_brl_per_mwh: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    pld_max_brl_per_mwh: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    pld_std_brl_per_mwh: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    hours_at_floor: Mapped[int] = mapped_column(Integer)
    hours_at_cap: Mapped[int] = mapped_column(Integer)
    hours: Mapped[int] = mapped_column(Integer)


class Distributor(Base):
    """A regulated distribution company (ANEEL). Companies only, no personal data."""

    __tablename__ = "distributor"

    cnpj: Mapped[str] = mapped_column(Text, primary_key=True)
    acronym: Mapped[str] = mapped_column(Text)


class ConsumerUnitSet(Base):
    """An electrical set of consumer units served by a distributor."""

    __tablename__ = "consumer_unit_set"

    distributor_cnpj: Mapped[str] = mapped_column(ForeignKey("distributor.cnpj"), primary_key=True)
    set_id: Mapped[str] = mapped_column(Text, primary_key=True)
    set_name: Mapped[str] = mapped_column(Text)


class ReliabilityMonthly(Base):
    """Monthly DEC (hours) and FEC (interruptions) per electrical set, with the year's limits."""

    __tablename__ = "reliability_monthly"
    __table_args__ = (
        ForeignKeyConstraint(
            ["distributor_cnpj", "set_id"],
            ["consumer_unit_set.distributor_cnpj", "consumer_unit_set.set_id"],
        ),
        CheckConstraint("dec_hours IS NULL OR dec_hours >= 0", name="dec"),
        CheckConstraint("fec_count IS NULL OR fec_count >= 0", name="fec"),
        Index("ix_reliability_monthly_distributor_cnpj", "distributor_cnpj"),
    )

    month: Mapped[date] = mapped_column(Date, primary_key=True)
    distributor_cnpj: Mapped[str] = mapped_column(Text, primary_key=True)
    set_id: Mapped[str] = mapped_column(Text, primary_key=True)
    consumers: Mapped[int | None] = mapped_column(BigInteger)
    dec_hours: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    fec_count: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    dec_limit_hours: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    fec_limit_count: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))


class TariffFlagMonthly(Base):
    """Tariff flag in force each month (ANEEL) and its additional charge, in R$ per MWh."""

    __tablename__ = "tariff_flag_monthly"
    __table_args__ = (CheckConstraint("additional_brl_per_mwh >= 0", name="additional"),)

    month: Mapped[date] = mapped_column(Date, primary_key=True)
    flag: Mapped[str] = mapped_column(Text)
    additional_brl_per_mwh: Mapped[Decimal] = mapped_column(Numeric(10, 2))


class MarketConsumptionMonthly(Base):
    """Consumption in the regulated (ACR) and free (ACL) markets, average MW (CCEE)."""

    __tablename__ = "market_consumption_monthly"
    __table_args__ = (
        CheckConstraint("regulated_mw_avg >= 0 AND free_mw_avg >= 0", name="positive"),
    )

    month: Mapped[date] = mapped_column(Date, primary_key=True)
    regulated_mw_avg: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    free_mw_avg: Mapped[Decimal] = mapped_column(Numeric(14, 3))


class MarketAgentsMonthly(Base):
    """Number of agents per class in the electricity market (CCEE)."""

    __tablename__ = "market_agents_monthly"
    __table_args__ = (CheckConstraint("agents >= 0", name="agents"),)

    month: Mapped[date] = mapped_column(Date, primary_key=True)
    agent_class: Mapped[str] = mapped_column(Text, primary_key=True)
    agents: Mapped[int] = mapped_column(Integer)
