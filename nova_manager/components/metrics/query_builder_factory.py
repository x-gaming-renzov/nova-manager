from nova_manager.components.metrics.artefacts import EventsArtefacts


def get_query_builder(backend: str, org_id: str, app_id: str) -> EventsArtefacts:
    """Return the appropriate query builder for the given analytics backend."""
    if backend == "adx":
        from nova_manager.components.metrics.kql_query_builder import KQLQueryBuilder
        return KQLQueryBuilder(org_id, app_id)

    from nova_manager.components.metrics.query_builder import QueryBuilder
    return QueryBuilder(org_id, app_id)
