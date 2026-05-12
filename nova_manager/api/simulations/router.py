from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from nova_manager.api.simulations.request_response import (
    CreateSimulationRequest,
    UpdateSimulationRequest,
    SimulationResponse,
    SimulationRunResponse,
    RunSimulationResponse,
)
from nova_manager.components.simulations.crud import SimulationsCRUD, SimulationRunsCRUD
from nova_manager.components.simulations.engine import compute_simulation
from nova_manager.components.metrics.events_controller import EventsController
from nova_manager.components.auth.dependencies import require_app_context
from nova_manager.core.security import AuthContext
from nova_manager.database.session import get_db


router = APIRouter()


@router.post("/", response_model=SimulationResponse)
async def create_simulation(
    data: CreateSimulationRequest,
    auth: AuthContext = Depends(require_app_context),
    db: Session = Depends(get_db),
):
    crud = SimulationsCRUD(db)

    # Check name uniqueness
    if crud.get_by_name(data.name, auth.organisation_id, auth.app_id):
        raise HTTPException(status_code=400, detail="Simulation with this name already exists")

    # Check scenario_id uniqueness
    if crud.get_by_scenario_id(data.scenario_id, auth.organisation_id, auth.app_id):
        raise HTTPException(status_code=400, detail="A simulation with this scenario_id already exists")

    simulation = crud.create({
        "name": data.name,
        "description": data.description,
        "scenario_id": data.scenario_id,
        "assumptions": data.assumptions,
        "organisation_id": auth.organisation_id,
        "app_id": auth.app_id,
    })
    return simulation


@router.get("/", response_model=List[SimulationResponse])
async def list_simulations(
    auth: AuthContext = Depends(require_app_context),
    status: Optional[str] = Query(None),
    skip: int = Query(0),
    limit: int = Query(100),
    db: Session = Depends(get_db),
):
    crud = SimulationsCRUD(db)
    return crud.get_multi_by_org(auth.organisation_id, auth.app_id, skip, limit, status)


@router.get("/{simulation_id}/", response_model=SimulationResponse)
async def get_simulation(
    simulation_id: UUID,
    auth: AuthContext = Depends(require_app_context),
    db: Session = Depends(get_db),
):
    crud = SimulationsCRUD(db)
    simulation = crud.get_by_pid(simulation_id)
    if not simulation or simulation.organisation_id != auth.organisation_id or simulation.app_id != auth.app_id:
        raise HTTPException(status_code=404, detail="Simulation not found")
    return simulation


@router.put("/{simulation_id}/", response_model=SimulationResponse)
async def update_simulation(
    simulation_id: UUID,
    data: UpdateSimulationRequest,
    auth: AuthContext = Depends(require_app_context),
    db: Session = Depends(get_db),
):
    crud = SimulationsCRUD(db)
    simulation = crud.get_by_pid(simulation_id)
    if not simulation or simulation.organisation_id != auth.organisation_id or simulation.app_id != auth.app_id:
        raise HTTPException(status_code=404, detail="Simulation not found")

    update_data = {}
    if data.name is not None:
        update_data["name"] = data.name
    if data.description is not None:
        update_data["description"] = data.description
    if data.assumptions is not None:
        update_data["assumptions"] = data.assumptions
    if data.status is not None:
        update_data["status"] = data.status

    if update_data:
        simulation = crud.update(simulation, update_data)
    return simulation


@router.delete("/{simulation_id}/")
async def delete_simulation(
    simulation_id: UUID,
    auth: AuthContext = Depends(require_app_context),
    db: Session = Depends(get_db),
):
    crud = SimulationsCRUD(db)
    simulation = crud.get_by_pid(simulation_id)
    if not simulation or simulation.organisation_id != auth.organisation_id or simulation.app_id != auth.app_id:
        raise HTTPException(status_code=404, detail="Simulation not found")
    crud.delete_by_pid(simulation_id)
    return {"success": True}


@router.post("/{simulation_id}/run/", response_model=RunSimulationResponse)
def run_simulation(
    simulation_id: UUID,
    auth: AuthContext = Depends(require_app_context),
    db: Session = Depends(get_db),
):
    sim_crud = SimulationsCRUD(db)
    run_crud = SimulationRunsCRUD(db)

    simulation = sim_crud.get_by_pid(simulation_id)
    if not simulation or simulation.organisation_id != auth.organisation_id or simulation.app_id != auth.app_id:
        raise HTTPException(status_code=404, detail="Simulation not found")

    # Create run record with frozen assumptions
    run = run_crud.create({
        "simulation_id": simulation.id,
        "status": "running",
        "assumptions_snapshot": simulation.assumptions,
    })

    try:
        # Compute derived metrics
        rows = compute_simulation(simulation.assumptions)

        # Write to ClickHouse
        controller = EventsController(auth.organisation_id, auth.app_id, auth.analytics_backend)
        controller.create_business_metrics_table()
        controller.ingest_business_metrics(rows, scenario_id=simulation.scenario_id)

        # Mark completed
        run_crud.update(run, {
            "status": "completed",
            "metrics_written": len(rows),
            "completed_at": datetime.now(timezone.utc),
        })

    except Exception as e:
        run_crud.update(run, {
            "status": "failed",
            "error_message": str(e)[:1000],
        })
        raise HTTPException(status_code=500, detail=f"Simulation failed: {e}")

    return RunSimulationResponse(
        run=SimulationRunResponse.model_validate(run),
        metrics_written=len(rows),
    )


@router.get("/{simulation_id}/runs/", response_model=List[SimulationRunResponse])
async def list_simulation_runs(
    simulation_id: UUID,
    auth: AuthContext = Depends(require_app_context),
    skip: int = Query(0),
    limit: int = Query(20),
    db: Session = Depends(get_db),
):
    sim_crud = SimulationsCRUD(db)
    simulation = sim_crud.get_by_pid(simulation_id)
    if not simulation or simulation.organisation_id != auth.organisation_id or simulation.app_id != auth.app_id:
        raise HTTPException(status_code=404, detail="Simulation not found")

    run_crud = SimulationRunsCRUD(db)
    return run_crud.get_runs_for_simulation(simulation.id, skip, limit)
