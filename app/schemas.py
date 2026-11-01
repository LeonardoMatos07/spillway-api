import re
import uuid
from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    EmailStr,
    Field,
    PlainSerializer,
    WithJsonSchema,
    model_validator,
)

MONTH_PATTERN = r"^\d{4}-(0[1-9]|1[0-2])$"
_MONTH_RE = re.compile(MONTH_PATTERN)

Source = Literal["wind", "solar"]
AggregateSource = Literal["wind", "solar", "total"]
Kind = Literal["plant", "cluster"]
SubsystemOrSin = Literal["N", "NE", "S", "SE", "SIN"]
RevalidateTag = Literal[
    "curtailment", "plants", "reports", "forecast", "news", "market", "reliability", "flag"
]
ALL_TAGS: list[RevalidateTag] = [
    "curtailment",
    "plants",
    "reports",
    "forecast",
    "news",
    "market",
    "reliability",
    "flag",
]


def parse_month(value: Any) -> date:
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.replace(day=1)
    if isinstance(value, str) and _MONTH_RE.match(value):
        return date(int(value[:4]), int(value[5:7]), 1)
    raise ValueError("month must use the YYYY-MM format")


def format_month(value: date) -> str:
    return value.strftime("%Y-%m")


Month = Annotated[
    date,
    BeforeValidator(parse_month),
    PlainSerializer(format_month, return_type=str),
    WithJsonSchema({"type": "string", "pattern": MONTH_PATTERN, "examples": ["2026-09"]}),
]


class _Orm(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class _CurtailmentAggregate(_Orm):
    source: AggregateSource
    month: Month
    verified_generation_mwh: float
    curtailed_mwh: float
    curtailment_pct: float | None
    curtailed_rel_mwh: float
    curtailed_cnf_mwh: float
    curtailed_ene_mwh: float
    curtailed_other_mwh: float
    estimated_loss_brl: float | None
    affected_plants: int
    updated_at: datetime


class SubsystemCurtailment(_CurtailmentAggregate):
    subsystem: str


class StateCurtailment(_CurtailmentAggregate):
    state: str


class PlantCurtailment(_Orm):
    plant_id: str
    month: Month
    verified_generation_mwh: float
    curtailed_mwh: float
    curtailment_pct: float | None
    curtailed_rel_mwh: float
    curtailed_cnf_mwh: float
    curtailed_ene_mwh: float
    curtailed_other_mwh: float
    estimated_loss_brl: float | None
    price_basis: str | None
    restricted_hours: float
    state_avg_curtailment_pct: float | None
    national_rank: int | None
    state_rank: int | None
    updated_at: datetime


class PlantSummary(_Orm):
    id: str
    kind: Kind
    name: str
    slug: str
    source: Source
    state: str
    subsystem: str
    capacity_mw: float | None


class Plant(PlantSummary):
    cluster_id: str | None
    ceg: str | None
    connection_point: str | None
    operator: str | None
    updated_at: datetime


class RankedPlant(PlantSummary):
    rank: int
    curtailed_mwh: float
    curtailment_pct: float | None
    estimated_loss_brl: float | None


class SubsystemCurtailmentResponse(BaseModel):
    items: list[SubsystemCurtailment]


class StateCurtailmentResponse(BaseModel):
    series: list[StateCurtailment]
    ranking: list[RankedPlant]
    ranking_month: Month | None


class CurtailmentSummary(BaseModel):
    scope: str
    source: AggregateSource
    start: Month | None
    end: Month | None
    months: int
    verified_generation_mwh: float
    curtailed_mwh: float
    curtailed_rel_mwh: float
    curtailed_cnf_mwh: float
    curtailed_ene_mwh: float
    curtailed_other_mwh: float
    curtailment_pct: float | None
    estimated_loss_brl: float | None
    affected_plants: int


class RankedGroup(BaseModel):
    rank: int
    name: str
    state: str | None
    plants: int
    affected_plants: int
    verified_generation_mwh: float
    curtailed_mwh: float
    curtailment_pct: float | None
    estimated_loss_brl: float | None
    compensable_mwh: float


class GroupRankingResponse(BaseModel):
    group: Literal["operator", "connection_point"]
    source: AggregateSource
    start: Month | None
    end: Month | None
    items: list[RankedGroup]


DayType = Literal["weekday", "weekend"]


class HourlyPoint(BaseModel):
    day_type: DayType
    hour: int
    avg_curtailed_mwh: float
    avg_generation_mwh: float
    curtailment_pct: float | None


class HourlyProfileResponse(BaseModel):
    scope: str
    source: AggregateSource
    start: Month | None
    end: Month | None
    months: int
    points: list[HourlyPoint]


class PlantListResponse(BaseModel):
    items: list[PlantSummary]
    total: int
    page: int
    page_size: int


class PlantDetailResponse(BaseModel):
    plant: Plant
    cluster: PlantSummary | None
    cluster_plants: list[PlantSummary]
    series: list[PlantCurtailment]


class RankingResponse(BaseModel):
    month: Month | None
    items: list[RankedPlant]


class MonthsResponse(BaseModel):
    months: list[Month]


class ReportSummary(_Orm):
    month: Month
    title: str
    slug: str
    summary: str | None
    published_at: datetime | None


class Report(ReportSummary):
    content: str


class AdminReport(Report):
    created_at: datetime
    updated_at: datetime


class ReportListResponse(BaseModel):
    items: list[ReportSummary]


class DispatchInput(BaseModel):
    kind: Literal["report", "analysis"]
    month: Month | None = Field(
        default=None, description="Defaults to the month of the latest published report."
    )
    retry: bool = Field(default=False, description="Finish a send that stopped partway.")


class Dispatch(_Orm):
    id: int
    kind: Literal["report", "analysis"]
    month: Month
    status: Literal["running", "done", "partial"]
    recipients: int
    sent: int
    failed: int
    started_at: datetime
    finished_at: datetime | None


class DispatchListResponse(BaseModel):
    items: list[Dispatch]


class AdminReportListResponse(BaseModel):
    items: list[AdminReport]


class ReportInput(BaseModel):
    month: Month
    title: str = Field(min_length=1, max_length=300)
    slug: str | None = Field(
        default=None,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
        max_length=200,
        description="Optional; generated from the title when missing.",
    )
    summary: str | None = None
    content: str = Field(min_length=1)
    publish: bool


class NewsletterSignup(BaseModel):
    email: EmailStr = Field(max_length=254)
    consent: Literal[True]
    source: str | None = Field(default=None, max_length=100)


class MessageResponse(BaseModel):
    message: str


class NewsletterPreference(BaseModel):
    enabled: bool


class ConfirmedResponse(BaseModel):
    confirmed: bool


class UnsubscribedResponse(BaseModel):
    unsubscribed: bool


class LoadRun(_Orm):
    id: int
    dataset: str
    period: Month | None
    source_file: str | None
    checksum: str | None
    row_count: int | None
    started_at: datetime
    finished_at: datetime | None
    status: Literal["running", "success", "failed"]
    detail: str | None


class LoadRunListResponse(BaseModel):
    items: list[LoadRun]


class RevalidateInput(BaseModel):
    tags: list[RevalidateTag] = Field(default_factory=lambda: list(ALL_TAGS))


class RevalidateResponse(BaseModel):
    tags: list[RevalidateTag]
    cache_cleared: bool
    entries_removed: int
    web_revalidated: bool
    detail: str | None


class HealthResponse(BaseModel):
    status: str
    database: str


Role = Literal[
    "researcher", "student", "professional", "journalist", "public_sector", "investor", "other"
]
Segment = Literal[
    "generator",
    "storage_developer",
    "trader",
    "consultancy",
    "financial",
    "consumer",
    "utility",
    "equipment",
    "law_regulatory",
    "other",
]
CompanySize = Literal["1-10", "11-50", "51-200", "201-1000", "1000+"]
StudyLevel = Literal["undergraduate", "master", "phd", "postdoc", "other"]
Region = Literal["Norte", "Nordeste", "Centro-Oeste", "Sudeste", "Sul"]
Interest = Literal[
    "monitor_losses",
    "compensation",
    "storage",
    "free_market",
    "investment",
    "data_api",
    "research",
    "press",
]
LeadTier = Literal["hot", "warm", "cold"]

MAX_LIST_ITEMS = 8
MAX_PLANTS = 5
PASSWORD_MIN_LENGTH = 10
PASSWORD_MAX_LENGTH = 128
ROLES_WITH_ORGANIZATION = frozenset({"professional", "investor"})
ROLES_WITH_INSTITUTION = frozenset({"student", "researcher"})


def _unique[T](values: list[T]) -> list[T]:
    return list(dict.fromkeys(values))


class MemberSignup(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: EmailStr = Field(max_length=254)
    password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)
    name: str = Field(min_length=2, max_length=120)
    role: Role
    organization: str | None = Field(default=None, max_length=150)
    job_title: str | None = Field(default=None, max_length=100)
    segment: Segment | None = None
    company_size: CompanySize | None = None
    institution: str | None = Field(default=None, max_length=150)
    study_level: StudyLevel | None = None
    regions: list[Region] = Field(default_factory=list, max_length=MAX_LIST_ITEMS)
    plants: list[Annotated[str, Field(min_length=1, max_length=120)]] = Field(
        default_factory=list, max_length=MAX_PLANTS
    )
    interests: list[Interest] = Field(default_factory=list, max_length=MAX_LIST_ITEMS)
    phone: str | None = Field(default=None, pattern=r"^[0-9+()\-\s]{8,20}$")
    referral: str | None = Field(default=None, max_length=100)
    marketing_opt_in: bool = False
    consent: Literal[True]
    source: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def _check_role_fields(self) -> "MemberSignup":
        if self.role in ROLES_WITH_ORGANIZATION and not self.organization:
            raise ValueError("organization is required for this role")
        if self.role in ROLES_WITH_INSTITUTION and not self.institution:
            raise ValueError("institution is required for this role")
        self.regions = _unique(self.regions)
        self.plants = _unique(self.plants)
        self.interests = _unique(self.interests)
        return self


class MemberLogin(BaseModel):
    email: EmailStr = Field(max_length=254)
    password: str = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)


class EmailVerification(BaseModel):
    email: EmailStr = Field(max_length=254)
    code: str = Field(pattern=r"^[0-9]{6}$")


class SignupResponse(BaseModel):
    message: str
    dev_code: str | None = None


class EmailOnly(BaseModel):
    email: EmailStr = Field(max_length=254)


class PasswordReset(BaseModel):
    email: EmailStr = Field(max_length=254)
    code: str = Field(pattern=r"^[0-9]{6}$")
    password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)


class PasswordConfirmation(BaseModel):
    password: str = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)


class VerifiedResponse(BaseModel):
    verified: bool


class MemberProfile(_Orm):
    id: uuid.UUID
    email: str
    name: str
    role: Role
    organization: str | None
    job_title: str | None
    segment: str | None
    institution: str | None
    regions: list[str]
    plants: list[str]
    interests: list[str]
    marketing_opt_in: bool
    created_at: datetime


class LoginResponse(BaseModel):
    session_token: str
    expires_at: datetime
    member: MemberProfile


class Lead(MemberProfile):
    company_size: str | None
    study_level: str | None
    phone: str | None
    referral: str | None
    signup_source: str | None
    email_verified_at: datetime | None
    lead_score: int
    lead_tier: LeadTier
    last_login_at: datetime | None


class LeadListResponse(BaseModel):
    items: list[Lead]
    total: int


EventCategory = Literal["page", "interaction", "auth", "newsletter", "admin", "system"]
IngestCategory = Literal["page", "interaction"]
ACTION_PATTERN = r"^[a-z0-9_.:-]{1,80}$"


class EventInput(BaseModel):
    category: IngestCategory = "interaction"
    action: str = Field(pattern=ACTION_PATTERN)
    path: str | None = Field(default=None, max_length=512)
    query: dict[str, str] | None = None
    section: str | None = Field(default=None, max_length=40)
    entity_type: str | None = Field(default=None, max_length=40)
    entity_id: str | None = Field(default=None, max_length=200)
    properties: dict[str, Any] = Field(default_factory=dict)


class EventBatch(BaseModel):
    events: list[EventInput] = Field(min_length=1, max_length=50)
    visitor_id: str | None = Field(default=None, max_length=64)
    session_key: str | None = Field(default=None, max_length=64)
    user_agent: str | None = Field(default=None, max_length=300)
    referrer: str | None = Field(default=None, max_length=512)
    request_id: str | None = Field(default=None, max_length=64)


class EventsAccepted(BaseModel):
    accepted: int


class UsageTotals(BaseModel):
    events: int
    page_views: int
    members_active: int
    visitors: int
    sessions: int
    new_members: int


class DailyUsage(BaseModel):
    day: date
    page_views: int
    interactions: int
    members: int


class SectionUsage(BaseModel):
    section: str
    views: int
    members: int


class EntityUsage(BaseModel):
    entity_type: str
    entity_id: str
    views: int
    members: int


class CountItem(BaseModel):
    name: str
    count: int


class FunnelStep(BaseModel):
    step: str
    count: int


class RoleUsage(BaseModel):
    role: str | None
    segment: str | None
    members: int
    events: int


class ActiveLead(BaseModel):
    member_id: uuid.UUID
    name: str
    email: str
    organization: str | None
    role: str
    lead_tier: str
    lead_score: int
    events: int
    last_seen: datetime | None


class UsageSummary(BaseModel):
    start: datetime
    end: datetime
    days: int
    include_bots: bool
    totals: UsageTotals
    daily: list[DailyUsage]
    sections: list[SectionUsage]
    entities: list[EntityUsage]
    searches: list[CountItem]
    interactions: list[CountItem]
    compared: list[CountItem]
    funnel: list[FunnelStep]
    roles: list[RoleUsage]
    active_leads: list[ActiveLead]


class UsageEventOut(_Orm):
    id: int
    occurred_at: datetime
    category: str
    action: str
    section: str | None
    entity_type: str | None
    entity_id: str | None
    path: str | None
    properties: dict[str, Any]
    member_id: uuid.UUID | None
    member_role: str | None
    member_segment: str | None
    visitor_id: str | None
    session_key: str | None
    device: str | None
    is_bot: bool
    referrer: str | None
    request_id: str | None


class UsageEventList(BaseModel):
    items: list[UsageEventOut]
    total: int


class MemberTimeline(BaseModel):
    member: Lead
    events: list[UsageEventOut]
    total: int


class PurgeResponse(BaseModel):
    deleted: int
    older_than_days: int


class ForecastPoint(BaseModel):
    ts: str = Field(description="Hour start, Brasilia local time (no offset)")
    risk_probability: float = Field(ge=0, le=1)
    expected_curtailment_pct: float
    level: Literal["baixo", "medio", "alto"]
    applicable: bool = Field(
        description="False for hours without expected generation (solar night)"
    )


class ForecastResponse(BaseModel):
    scope: str
    source: Source
    risk_definition: str
    origin_ts: str
    valid_from: str = Field(description="First hour returned (Brasilia time)")
    valid_to: str = Field(description="Last hour returned (Brasilia time)")
    generated_at: datetime
    data_through: date = Field(description="Last day of ONS data behind this forecast")
    stale_days: int
    model_version: str
    model_trained_at: datetime
    points: list[ForecastPoint]


class ForecastScope(BaseModel):
    scope: str
    source: Source


class ForecastModelResponse(BaseModel):
    model_version: str
    trained_at: datetime
    data_period: dict[str, Any]
    n_series: int
    n_rows: int
    metrics: dict[str, Any]
    calibration: dict[str, Any]
    feature_importance: dict[str, Any]
    model_card: dict[str, Any]
    last_run_at: datetime | None
    last_data_through: date | None


GenerationSource = Literal["hydro", "thermal", "wind", "solar"]
Subsystem = Literal["N", "NE", "S", "SE"]


class BalancePoint(_Orm):
    hour: datetime
    hour_utc: datetime
    subsystem: Subsystem
    hydro_mw_avg: float | None
    thermal_mw_avg: float | None
    wind_mw_avg: float | None
    solar_mw_avg: float | None
    load_mw_avg: float | None
    net_interchange_mw_avg: float | None


class BalanceResponse(BaseModel):
    date_from: date
    date_to: date
    points: list[BalancePoint]


class MonthlyGenerationPoint(_Orm):
    month: Month
    subsystem: SubsystemOrSin
    source: GenerationSource
    energy_mwh: float
    avg_mw: float
    peak_mw: float
    share_pct: float | None


class MonthlyGenerationResponse(BaseModel):
    points: list[MonthlyGenerationPoint]


class PowerPlantInfo(_Orm):
    id: str
    name: str
    slug: str
    source_type: str
    fuel_type: str | None
    state: str | None
    subsystem: str | None
    capacity_mw: float | None


class PlantGenerationPoint(_Orm):
    month: Month
    energy_mwh: float
    avg_mw: float
    peak_mw: float
    capacity_factor: float | None


class PlantGenerationResponse(BaseModel):
    plant: PowerPlantInfo
    points: list[PlantGenerationPoint]


InterchangeScope = Literal["national", "international"]
ThermalReason = str


class InterchangeMonthlyPoint(_Orm):
    month: Month
    origin: str
    destination: str
    scope: InterchangeScope
    energy_mwh: float
    scheduled_energy_mwh: float | None
    avg_mw: float
    peak_mw: float
    min_mw: float


class InterchangeMonthlyResponse(BaseModel):
    points: list[InterchangeMonthlyPoint]


class InterchangeHourlyPoint(_Orm):
    hour: datetime
    hour_utc: datetime
    origin: str
    destination: str
    scope: InterchangeScope
    flow_mw_avg: float | None
    scheduled_mw_avg: float | None


class InterchangeHourlyResponse(BaseModel):
    date_from: date
    date_to: date
    points: list[InterchangeHourlyPoint]


class ThermalDispatchPoint(BaseModel):
    month: Month
    reason: str
    subsystem: str
    plant_code: str | None
    plant_name: str | None
    plants: int
    verified_mwh: float
    programmed_mwh: float | None


class ThermalDispatchResponse(BaseModel):
    points: list[ThermalDispatchPoint]


class SubsystemStoragePoint(_Orm):
    day: date
    subsystem: Subsystem
    storage_max_mw_month: float | None
    storage_mw_month: float | None
    storage_pct: float | None
    ena_gross_mw_avg: float | None
    ena_gross_pct_mlt: float | None
    ena_storable_mw_avg: float | None
    ena_storable_pct_mlt: float | None


class SubsystemStorageResponse(BaseModel):
    date_from: date
    date_to: date
    points: list[SubsystemStoragePoint]


class ReservoirInfo(_Orm):
    id: str
    name: str
    slug: str
    reservoir_type: str | None
    plant_name: str | None
    ceg: str | None
    subsystem: str | None
    ree: str | None
    basin: str | None
    river: str | None
    commissioned_on: date | None
    useful_volume_hm3: float | None
    max_level_m: float | None
    min_level_m: float | None
    latitude: float | None
    longitude: float | None


class ReservoirSummary(ReservoirInfo):
    latest_day: date | None
    storage_pct: float | None
    ena_storable_pct_mlt: float | None


class ReservoirListResponse(BaseModel):
    latest_day: date | None
    items: list[ReservoirSummary]


class ReservoirDailyPoint(_Orm):
    day: date
    storage_mw_month: float | None
    storage_max_mw_month: float | None
    storage_pct: float | None
    useful_volume_pct: float | None
    ena_gross_mw_avg: float | None
    ena_gross_pct_mlt: float | None
    ena_storable_mw_avg: float | None
    ena_storable_pct_mlt: float | None
    inflow_m3s: float | None
    natural_inflow_m3s: float | None
    outflow_m3s: float | None
    turbined_m3s: float | None
    spilled_m3s: float | None
    upstream_level_m: float | None
    downstream_level_m: float | None


class ReservoirDetailResponse(BaseModel):
    date_from: date
    date_to: date
    reservoir: ReservoirInfo
    points: list[ReservoirDailyPoint]


class SpilledEnergyPoint(_Orm):
    month: Month
    plant_code: str
    plant_name: str
    subsystem: str | None
    basin: str | None
    river: str | None
    agent: str | None
    spilled_energy_mwh: float
    spilled_turbinable_energy_mwh: float


class SpilledEnergyResponse(BaseModel):
    points: list[SpilledEnergyPoint]


class GridVersion(_Orm):
    valid_from: date
    valid_to: date | None


class TransmissionLineItem(GridVersion):
    equipment_code: str
    name: str | None
    voltage_kv: float | None
    line_type: str | None
    network_type: str | None
    owner_agent: str | None
    from_substation: str | None
    to_substation: str | None
    from_subsystem: str | None
    to_subsystem: str | None
    from_state: str | None
    to_state: str | None
    length_km: float | None
    capacity_long_no_limit_a: float | None
    capacity_long_with_limit_a: float | None
    capacity_short_no_limit_a: float | None
    capacity_short_with_limit_a: float | None
    positive_seq_resistance: float | None
    positive_seq_reactance: float | None
    positive_seq_shunt: float | None
    commissioned_on: date | None
    decommissioned_on: date | None
    planned_on: date | None


class TransmissionLineListResponse(BaseModel):
    as_of: date | None
    total: int
    page: int
    page_size: int
    items: list[TransmissionLineItem]


class SubstationItem(GridVersion):
    station_id: str
    substation_id: str | None
    name: str | None
    voltage_kv: float | None
    subsystem: str | None
    state: str | None
    main_agent: str | None
    bus_number: int | None
    latitude: float | None
    longitude: float | None


class SubstationListResponse(BaseModel):
    as_of: date | None
    total: int
    page: int
    page_size: int
    items: list[SubstationItem]


NewsStatus = Literal["published", "hidden", "removed_on_request"]


class NewsSource(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    slug: str
    publisher_name: str
    homepage_url: str
    fetch_method: str
    license_code: str
    license_url: str
    license_verified_at: datetime | None
    license_evidence_url: str | None
    active: bool


class NewsSourceListResponse(BaseModel):
    items: list[NewsSource]


class RelatedLink(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    href: str = Field(min_length=1, max_length=300, pattern=r"^(/|https://)")


class NewsItem(BaseModel):
    """A news item exactly as the source published it, with everything needed to cite it."""

    id: int
    source: str
    publisher_name: str
    license_code: str
    license_url: str
    url: str
    title: str
    summary: str | None
    published_at: datetime
    source_updated_at: datetime | None
    topics: list[str]
    has_editor_note: bool


class NewsItemDetail(NewsItem):
    editor_note: str | None
    editor_note_by: str | None
    editor_note_at: datetime | None
    related_links: list[RelatedLink]


class NewsListResponse(BaseModel):
    items: list[NewsItem]
    next_cursor: str | None


class AdminNewsItem(NewsItemDetail):
    status: NewsStatus


class AdminNewsList(BaseModel):
    items: list[AdminNewsItem]
    next_cursor: str | None


class NewsPatch(BaseModel):
    """Moderation: hide an item, write the editor note (by a person), link Spillway pages."""

    model_config = ConfigDict(extra="forbid")

    status: NewsStatus | None = None
    editor_note: str | None = Field(default=None, max_length=2000)
    clear_editor_note: bool = False
    related_links: list[RelatedLink] | None = Field(default=None, max_length=8)


class RegulatoryAct(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organ: str
    act_type: str
    act_number: str | None
    act_date: date | None
    title: str
    summary: str | None
    dou_date: date
    dou_section: int | None
    dou_edition: str | None
    dou_page: str | None
    dou_url: str
    topics: list[str]


class RegulatoryActDetail(RegulatoryAct):
    body: str | None


class RegulatoryActListResponse(BaseModel):
    items: list[RegulatoryAct]
    next_cursor: str | None


class RegulatoryActPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: NewsStatus


class DataSourceInfo(_Orm):
    """Publisher, license and attribution of a dataset (shown on every screen that uses it)."""

    slug: str
    publisher_name: str
    dataset_name: str
    dataset_url: str
    license_code: str
    license_url: str
    license_verified_at: date
    attribution_text: str
    update_frequency: str


PldGranularity = Literal["hourly", "daily", "weekly", "monthly"]
PldVariant = Literal["official", "shadow"]


class PldPoint(BaseModel):
    """One PLD value. Hourly and weekly points have no min, max or counts."""

    period: str  # ISO date (daily, weekly, monthly) or local date-time (hourly)
    subsystem: Subsystem
    pld_avg_brl_per_mwh: float
    pld_min_brl_per_mwh: float | None = None
    pld_max_brl_per_mwh: float | None = None
    pld_std_brl_per_mwh: float | None = None
    hours_at_floor: int | None = None
    hours_at_cap: int | None = None
    hours: int | None = None


class PldResponse(BaseModel):
    granularity: PldGranularity
    variant: PldVariant
    date_from: date
    date_to: date
    source: DataSourceInfo
    points: list[PldPoint]


class ReliabilityDistributor(BaseModel):
    """Annual indicators of a distributor, weighted by the consumers of each electrical set."""

    cnpj: str
    acronym: str
    consumers: int
    dec_hours: float
    fec_count: float
    dec_limit_hours: float | None
    fec_limit_count: float | None
    months_with_data: int
    sets: int


class ReliabilityResponse(BaseModel):
    year: int
    years: list[int]
    months_with_data: int
    source: DataSourceInfo
    items: list[ReliabilityDistributor]


class ReliabilityMonthPoint(BaseModel):
    month: date
    consumers: int
    dec_hours: float
    fec_count: float


class ReliabilityDetailResponse(BaseModel):
    year: int
    years: list[int]
    distributor: ReliabilityDistributor
    source: DataSourceInfo
    points: list[ReliabilityMonthPoint]


class TariffFlagPoint(_Orm):
    month: date
    flag: str
    additional_brl_per_mwh: float


class TariffFlagsResponse(BaseModel):
    """Tariff flags month by month. The charge is on top of the homologated tariff, before taxes."""

    source: DataSourceInfo
    items: list[TariffFlagPoint]


class MarketConsumptionPoint(_Orm):
    month: date
    regulated_mw_avg: float
    free_mw_avg: float
    free_share_pct: float


class MarketAgentsPoint(_Orm):
    month: date
    agent_class: str
    agents: int


class MarketConsumptionResponse(BaseModel):
    source: DataSourceInfo
    consumption: list[MarketConsumptionPoint]
    agents: list[MarketAgentsPoint]


class GeoStateCurtailment(_Orm):
    state: str
    curtailment_pct: float | None
    curtailed_mwh: float
    verified_generation_mwh: float
    estimated_loss_brl: float | None
    affected_plants: int


class GeoStatesMeta(_Orm):
    """Where a map layer comes from; `omitted` counts the states that could not be drawn."""

    source_name: str
    source_url: str
    license: str
    data_source: AggregateSource
    month: Month | None
    months: list[Month]
    updated_at: datetime | None
    warnings: list[str]
    omitted: int
    omitted_states: list[str]


class GeoStatesResponse(_Orm):
    meta: GeoStatesMeta
    items: list[GeoStateCurtailment]
