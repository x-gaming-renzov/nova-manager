from nova_manager.components.metrics.artefacts import EventsArtefacts
from nova_manager.core.config import ADX_DATABASE


def get_query_builder(backend: str, org_id: str, app_id: str) -> EventsArtefacts:
    """Return the appropriate query builder for the given analytics backend."""
    if backend == "adx":
        from nova_manager.components.metrics.kql_query_builder import KQLQueryBuilder
        # Use shared-DB mode when ADX_DATABASE is set (no per-org/app DB yet)
        use_shared_db = bool(ADX_DATABASE)
        return KQLQueryBuilder(org_id, app_id, use_shared_db=use_shared_db)

    from nova_manager.components.metrics.query_builder import QueryBuilder
    return QueryBuilder(org_id, app_id)
