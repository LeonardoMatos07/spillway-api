"""Approximate position of a plant: the substation it connects to (or an official point later)."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "plant_location",
        sa.Column("plant_id", sa.Text(), nullable=False),
        sa.Column("latitude", sa.Numeric(10, 6), nullable=False),
        sa.Column("longitude", sa.Numeric(10, 6), nullable=False),
        sa.Column("location_precision", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("matched_on", sa.Text(), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "location_precision IN ('substation', 'official')",
            name="ck_plant_location_location_precision",
        ),
        sa.CheckConstraint(
            "latitude BETWEEN -34 AND 6 AND longitude BETWEEN -74 AND -34",
            name="ck_plant_location_inside_brazil",
        ),
        sa.ForeignKeyConstraint(
            ["plant_id"],
            ["plant.id"],
            name="fk_plant_location_plant_id_plant",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("plant_id", name="pk_plant_location"),
    )


def downgrade() -> None:
    op.drop_table("plant_location")
