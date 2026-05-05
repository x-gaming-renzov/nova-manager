from typing import Optional
from uuid import UUID as UUIDType

from sqlalchemy.orm import Session

from nova_manager.core.base_crud import BaseCRUD
from nova_manager.components.simulations.models import Simulations, SimulationRuns


class SimulationsCRUD(BaseCRUD):
    def __init__(self, db: Session):
        super().__init__(Simulations, db)

    def get_by_name(self, name: str, organisation_id: str, app_id: str) -> Optional[Simulations]:
        return (
            self.db.query(Simulations)
            .filter(
                Simulations.name == name,
                Simulations.organisation_id == organisation_id,
                Simulations.app_id == app_id,
            )
            .first()
        )

    def get_by_scenario_id(self, scenario_id: str, organisation_id: str, app_id: str) -> Optional[Simulations]:
        return (
            self.db.query(Simulations)
            .filter(
                Simulations.scenario_id == scenario_id,
                Simulations.organisation_id == organisation_id,
                Simulations.app_id == app_id,
            )
            .first()
        )

    def get_multi_by_org(
        self,
        organisation_id: str,
        app_id: str,
        skip: int = 0,
        limit: int = 100,
        status: Optional[str] = None,
    ) -> list[Simulations]:
        query = self.db.query(Simulations).filter(
            Simulations.organisation_id == organisation_id,
            Simulations.app_id == app_id,
        )
        if status:
            query = query.filter(Simulations.status == status)
        return query.order_by(Simulations.created_at.desc()).offset(skip).limit(limit).all()


class SimulationRunsCRUD(BaseCRUD):
    def __init__(self, db: Session):
        super().__init__(SimulationRuns, db)

    def get_runs_for_simulation(
        self, simulation_id: int, skip: int = 0, limit: int = 20
    ) -> list[SimulationRuns]:
        return (
            self.db.query(SimulationRuns)
            .filter(SimulationRuns.simulation_id == simulation_id)
            .order_by(SimulationRuns.created_at.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )
