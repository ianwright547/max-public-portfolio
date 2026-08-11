from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from scripts import check_search_console_connections


class FakeSearchConsole:
    def __init__(self):
        self.calls = []

    def read_report(self, property_url, start_date, end_date):
        self.calls.append((property_url, start_date, end_date))
        from app.google_search_console_service import SearchConsoleMetrics, SearchConsoleReport

        return SearchConsoleReport(SearchConsoleMetrics(3, 20, has_data=True))


def _database():
    engine = create_engine("sqlite://")
    models.Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_search_console_probe_queries_active_properties_only():
    with _database() as database_session:
        active = models.Client(business_name="Active Search", service_start_date=date(2026, 1, 1), status="active")
        archived = models.Client(business_name="Archived Search", service_start_date=date(2026, 1, 1), status="archived")
        archived.archived_at = date(2026, 2, 1)
        database_session.add_all([active, archived])
        database_session.flush()
        database_session.add_all(
            [
                models.SearchConsoleConnection(client_id=active.id, property_url="sc-domain:active.example"),
                models.SearchConsoleConnection(client_id=archived.id, property_url="sc-domain:archived.example"),
            ]
        )
        database_session.commit()
        adapter = FakeSearchConsole()

        result = check_search_console_connections.verify_connections(
            database_session, adapter=adapter, end_date=date(2026, 8, 20)
        )

        assert result["status"] == "verified"
        assert result["checked_properties"] == 1
        assert result["properties_with_data"] == 1
        assert adapter.calls == [("sc-domain:active.example", "2026-08-14", "2026-08-20")]


def test_search_console_probe_skips_when_no_active_properties():
    with _database() as database_session:
        assert check_search_console_connections.verify_connections(database_session)["status"] == "skipped"
