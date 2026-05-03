from typing import Dict, List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from nova_manager.api.metrics.request_response import (
    CreateMetricRequest,
    ComputeMetricRequest,
    EventsSchemaResponse,
    IngestBusinessDataRequest,
    MetricResponse,
    TrackEventRequest,
    TrackEventsRequest,
    UserProfileKeyResponse,
)
from nova_manager.components.metrics.crud import (
    MetricsCRUD,
    EventsSchemaCRUD,
    UserProfileKeysCRUD,
)
from nova_manager.components.metrics.events_controller import EventsController
from nova_manager.components.metrics.query_builder import QueryBuilder
from nova_manager.components.segments.crud import SegmentsCRUD
from nova_manager.components.metrics.query_builder import KeySource
from nova_manager.database.session import get_db
from nova_manager.service.clickhouse_service import ClickHouseService
from nova_manager.queues.controller import QueueController
from nova_manager.components.auth.dependencies import (
    require_app_context,
    require_sdk_app_context,
)
from nova_manager.core.security import AuthContext, SDKAuthContext
from sqlalchemy.orm import Session


router = APIRouter()


@router.post("/track-event/")
async def track_event(
    event: TrackEventRequest, auth: SDKAuthContext = Depends(require_sdk_app_context)
):
    # Enqueue background job using organisation/app from API key
    QueueController().add_task(
        EventsController(auth.organisation_id, auth.app_id).track_event,
        event.user_id,
        event.event_name,
        event.event_data,
        event.timestamp,
    )

    return {"success": True}


@router.post("/track-events/")
async def track_events(
    request: TrackEventsRequest,
    auth: SDKAuthContext = Depends(require_sdk_app_context),
):
    """Track multiple events in a single request."""
    events = [
        {
            "event_name": e.event_name,
            "event_data": e.event_data,
            "timestamp": e.timestamp,
        }
        for e in request.events
    ]

    QueueController().add_task(
        EventsController(auth.organisation_id, auth.app_id).track_events,
        request.user_id,
        events,
    )

    return {"success": True, "count": len(events)}


@router.post("/compute/", response_model=List[Dict])
async def compute_metric(
    compute_request: ComputeMetricRequest,
    auth: AuthContext = Depends(require_app_context),
    db: Session = Depends(get_db),
):
    organisation_id = auth.organisation_id
    app_id = auth.app_id
    type = compute_request.type
    # copy config and extract any segment filters embedded in filters
    # copy config and extract filters
    config = compute_request.config.copy()
    filters = config.get("filters", {}) or {}
    # extract explicit segment_ids list from config
    config_segment_ids = config.pop("segment_ids", []) or []
    # identify segment filters embedded in filters by source flag
    filter_segment_ids = [sid for sid, f in filters.items() if isinstance(f, dict) and f.get("source") == "segment"]
    # combine both sources of segment ids
    segment_ids = list(set(config_segment_ids + filter_segment_ids))
    # remove any placeholder entries from filters
    for sid in filter_segment_ids:
        filters.pop(sid, None)
    # merge each segment's conditions into filters
    if segment_ids:
        op_map = {"equals": "=", "not_equals": "!=", "gt": ">", "lt": "<", "gte": ">=", "lte": "<="}
        for sid in segment_ids:
            segment = SegmentsCRUD(db).get_by_pid(sid)
            if not segment:
                raise HTTPException(status_code=404, detail=f"Segment {sid} not found")
            for cond in segment.rule_config.get("conditions", []):
                key = cond["field"]
                op = op_map.get(cond["operator"], "=")
                filters[key] = {
                    "value": cond.get("value"),
                    "op": op,
                    "source": KeySource.USER_PROFILE,
                }
    # update config filters without segment placeholders
    config["filters"] = filters

    # extract personalisation_ids array and move first value into filters
    personalisation_ids = config.pop("personalisation_ids", None)
    if personalisation_ids:
        # take the first id and add as user_experience filter
        first_id = personalisation_ids[0]
        filters = config.setdefault("filters", {})
        filters["personalisation_id"] = {
            "value": first_id,
            "source": "user_experience",
            "op": "=",
        }

    query_builder = QueryBuilder(organisation_id, app_id)
    query = query_builder.build_query(type, config)

    clickhouse_service = ClickHouseService()
    result = clickhouse_service.run_query(query)

    return result


@router.get("/events-schema/", response_model=List[EventsSchemaResponse])
async def list_events_schema(
    auth: AuthContext = Depends(require_app_context),
    search: str = Query(None),
    db: Session = Depends(get_db),
):
    """Get all events schema for an organization/app with optional search"""
    events_schema_crud = EventsSchemaCRUD(db)

    if search:
        events_schema = events_schema_crud.search_events_schema(
            organisation_id=str(auth.organisation_id),
            app_id=auth.app_id,
            search_term=search,
            skip=0,
            limit=100,
        )
    else:
        events_schema = events_schema_crud.get_multi_by_org(
            organisation_id=str(auth.organisation_id),
            app_id=auth.app_id,
            skip=0,
            limit=100,
        )

    return events_schema


@router.get("/user-profile-keys/", response_model=List[UserProfileKeyResponse])
async def list_user_profile_keys(
    auth: AuthContext = Depends(require_app_context),
    search: str = Query(None),
    db: Session = Depends(get_db),
):
    """Get all user profile keys for an organization/app with optional search"""
    user_profile_keys_crud = UserProfileKeysCRUD(db)

    if search:
        user_profile_keys = user_profile_keys_crud.search_user_profile_keys(
            organisation_id=auth.organisation_id,
            app_id=auth.app_id,
            search_term=search,
            skip=0,
            limit=100,
        )
    else:
        user_profile_keys = user_profile_keys_crud.get_multi_by_org(
            organisation_id=auth.organisation_id,
            app_id=auth.app_id,
            skip=0,
            limit=100,
        )

    return user_profile_keys


@router.post("/business-data/")
async def ingest_business_data(
    request: IngestBusinessDataRequest,
    auth: AuthContext = Depends(require_app_context),
):
    """Ingest operational/business data (marketing spend, payouts, revenue, etc.)."""
    controller = EventsController(auth.organisation_id, auth.app_id)
    controller.create_business_metrics_table()
    rows = [
        {
            "metric_name": item.metric_name,
            "dimension": item.dimension,
            "value": item.value,
            "period_start": item.period_start.isoformat(),
            "currency": item.currency,
        }
        for item in request.data
    ]
    try:
        controller.ingest_business_metrics(rows)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"success": True, "count": len(rows)}


@router.get("/business-data/schema/")
async def list_business_data_schema(
    auth: AuthContext = Depends(require_app_context),
):
    """List distinct metric_name + dimension pairs from business_metrics table."""
    controller = EventsController(auth.organisation_id, auth.app_id)
    controller.create_business_metrics_table()
    table = controller._business_metrics_table_name()
    query = f"SELECT DISTINCT metric_name, dimension FROM {table} FINAL ORDER BY metric_name, dimension"
    result = ClickHouseService().run_query(query)
    return result


@router.post("/")
async def create_metric(
    metric_data: CreateMetricRequest,
    auth: AuthContext = Depends(require_app_context),
    db: Session = Depends(get_db),
):
    metrics_crud = MetricsCRUD(db)

    organisation_id = str(auth.organisation_id)
    app_id = auth.app_id
    name = metric_data.name
    description = metric_data.description
    type = metric_data.type
    config = metric_data.config

    metric = metrics_crud.create(
        {
            "organisation_id": organisation_id,
            "app_id": app_id,
            "name": name,
            "description": description,
            "type": type,
            "config": config,
        }
    )

    return metric


@router.get("/", response_model=List[MetricResponse])
async def list_metric(
    auth: AuthContext = Depends(require_app_context),
    db: Session = Depends(get_db),
):
    metrics_crud = MetricsCRUD(db)

    metrics = metrics_crud.get_multi(
        organisation_id=auth.organisation_id, app_id=auth.app_id
    )

    return metrics


@router.get("/{metric_id}/", response_model=MetricResponse)
async def get_metric(
    metric_id: UUID,
    auth: AuthContext = Depends(require_app_context),
    db: Session = Depends(get_db),
):
    metrics_crud = MetricsCRUD(db)

    metric = metrics_crud.get_by_pid(metric_id)

    if not metric:
        raise HTTPException(status_code=404, detail="Metric not found")

    return metric


@router.put("/{metric_id}/", response_model=MetricResponse)
async def update_metric(
    metric_id: UUID,
    metric_data: CreateMetricRequest,
    auth: AuthContext = Depends(require_app_context),
    db: Session = Depends(get_db),
):
    metrics_crud = MetricsCRUD(db)

    # Check if metric exists
    existing_metric = metrics_crud.get_by_pid(metric_id)
    if not existing_metric:
        raise HTTPException(status_code=404, detail="Metric not found")

    # Update the metric
    update_data = {
        "name": metric_data.name,
        "description": metric_data.description,
        "type": metric_data.type,
        "config": metric_data.config,
    }

    updated_metric = metrics_crud.update(existing_metric, update_data)

    return updated_metric
