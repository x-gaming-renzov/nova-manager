from nova_manager.service.analytics_service import AnalyticsService


def get_analytics_service(backend: str) -> AnalyticsService:
    if backend == "adx":
        from nova_manager.service.adx_service import ADXService
        return ADXService()

    from nova_manager.service.clickhouse_service import ClickHouseService
    return ClickHouseService()
