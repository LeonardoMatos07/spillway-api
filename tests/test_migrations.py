import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, inspect

from tests.conftest import ROOT, TEST_DATABASE_URL

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="requires TEST_DATABASE_URL (Postgres)"
)

TABLES = {
    "plant",
    "plant_location",
    "plant_monthly_curtailment",
    "state_monthly_curtailment",
    "subsystem_monthly_curtailment",
    "load_run",
    "subsystem_hourly_balance",
    "subsystem_monthly_generation",
    "power_plant",
    "plant_monthly_generation",
    "interchange_hourly",
    "interchange_monthly",
    "thermal_dispatch_monthly",
    "reservoir",
    "subsystem_storage_daily",
    "reservoir_daily",
    "plant_monthly_spilled_energy",
    "transmission_line",
    "substation",
    "transformer_capacity",
    "data_source",
    "pld_hourly",
    "pld_weekly",
    "pld_daily",
    "pld_monthly",
    "distributor",
    "consumer_unit_set",
    "reliability_monthly",
    "tariff_flag_monthly",
    "market_consumption_monthly",
    "market_agents_monthly",
    "monthly_report",
    "newsletter_subscriber",
    "organization",
    "app_user",
    "news_source",
    "news_item",
    "regulatory_act",
    "flag_rule_month",
    "flag_forecast_run",
    "flag_forecast_prob",
    "flag_forecast_input",
    "flag_forecast_score",
}


def _config(engine: Engine) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    url = engine.url.render_as_string(hide_password=False)
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


def test_downgrade_upgrade_roundtrip_and_no_drift(pg_engine: Engine) -> None:
    config = _config(pg_engine)
    command.downgrade(config, "base")
    assert TABLES.isdisjoint(inspect(pg_engine).get_table_names(schema="public"))
    command.upgrade(config, "head")
    assert set(inspect(pg_engine).get_table_names(schema="public")) >= TABLES
    command.check(config)
