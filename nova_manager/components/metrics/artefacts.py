import re


class EventsArtefacts:
    def __init__(self, organisation_id: str, app_id: str):
        self.organisation_id = organisation_id
        self.app_id = app_id
        self.database_name = self._database_name()

    def _database_name(self) -> str:
        # Build a ClickHouse-safe database name
        safe_org = self._sanitized_string(self.organisation_id)
        safe_app = self._sanitized_string(self.app_id)
        return f"org_{safe_org}_app_{safe_app}"

    def _sanitized_string(self, s: str):
        return re.sub(r"[^a-zA-Z0-9_]", "_", s)

    def _raw_events_table_name(self) -> str:
        return f"{self.database_name}.raw_events"

    def _event_props_table_name(self) -> str:
        return f"{self.database_name}.event_props"

    def _user_experience_table_name(self) -> str:
        return f"{self.database_name}.user_experience"

    def _user_profile_props_table_name(self) -> str:
        return f"{self.database_name}.user_profile_props"

    def _business_metrics_table_name(self) -> str:
        return f"{self.database_name}.business_metrics"
