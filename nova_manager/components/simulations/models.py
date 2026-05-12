from datetime import datetime
from sqlalchemy import (
    DateTime,
    Integer,
    JSON,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from nova_manager.core.models import BaseModel, BaseOrganisationModel


class Simulations(BaseOrganisationModel):
    __tablename__ = "simulations"

    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False, default="")
    scenario_id: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="draft")
    assumptions: Mapped[dict] = mapped_column(
        JSON, nullable=False, server_default=func.json("{}")
    )

    runs: Mapped[list["SimulationRuns"]] = relationship(
        "SimulationRuns", back_populates="simulation", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint(
            "name", "organisation_id", "app_id",
            name="uq_simulations_name_org_app",
        ),
        UniqueConstraint(
            "scenario_id", "organisation_id", "app_id",
            name="uq_simulations_scenario_id_org_app",
        ),
        Index("idx_simulations_org_app", "organisation_id", "app_id"),
    )


class SimulationRuns(BaseModel):
    __tablename__ = "simulation_runs"

    simulation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("simulations.id"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String, nullable=False, default="running")
    assumptions_snapshot: Mapped[dict] = mapped_column(
        JSON, nullable=False, server_default=func.json("{}")
    )
    metrics_written: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(String, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    simulation: Mapped["Simulations"] = relationship(
        "Simulations", back_populates="runs"
    )

    __table_args__ = (
        Index("idx_simulation_runs_simulation_id", "simulation_id"),
    )
