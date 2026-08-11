"""Import confirmed Vercel clients and website links without deploying anything."""

import argparse
import json
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import func, or_, select

from app import models
from app.database import SessionLocal, create_database


MANIFEST = Path(__file__).parent.parent / "data" / "vercel_client_import.json"


REQUIRED_FIELDS = {
    "business_name",
    "service_start_date",
    "project_created_at",
    "external_project_id",
    "project_name",
    "production_url",
}


def read_manifest(path: Path = MANIFEST) -> list[dict]:
    """Read and validate the confirmed website manifest before touching the database."""
    records = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(records, list) or not records:
        raise ValueError("The website manifest must contain at least one record")

    seen_businesses: set[str] = set()
    seen_projects: set[str] = set()
    for position, item in enumerate(records, start=1):
        missing = REQUIRED_FIELDS - item.keys()
        if missing:
            raise ValueError(f"Manifest record {position} is missing: {', '.join(sorted(missing))}")
        business_key = item["business_name"].strip().casefold()
        if not business_key:
            raise ValueError(f"Manifest record {position} has an empty business name")
        if business_key in seen_businesses:
            raise ValueError(f"Duplicate business name in manifest: {item['business_name']}")
        if item["external_project_id"] in seen_projects:
            raise ValueError(f"Duplicate external project in manifest: {item['external_project_id']}")
        if not item["production_url"].startswith("https://"):
            raise ValueError(f"Production URL must use HTTPS: {item['production_url']}")
        # Parse now so malformed dates fail before any database write.
        date.fromisoformat(item["service_start_date"])
        datetime.fromisoformat(item["project_created_at"].replace("Z", "+00:00"))
        seen_businesses.add(business_key)
        seen_projects.add(item["external_project_id"])
    return records


def import_clients(*, dry_run: bool = False) -> list[tuple[str, str, str]]:
    records = read_manifest()
    imported = []
    create_database()

    with SessionLocal() as database:
        try:
            for item in records:
                project_created = datetime.fromisoformat(item["project_created_at"].replace("Z", "+00:00"))
                service_start = date.fromisoformat(item["service_start_date"])
                if (service_start.year, service_start.month, service_start.day) != (
                    project_created.year,
                    project_created.month,
                    1,
                ):
                    raise ValueError(f"Invalid inferred service month for {item['business_name']}")

                client = database.scalar(
                    select(models.Client).where(
                        func.lower(models.Client.business_name) == item["business_name"].lower()
                    )
                )
                if client is None:
                    client = models.Client(
                        business_name=item["business_name"],
                        service_start_date=service_start,
                    )
                    database.add(client)
                    database.flush()
                elif client.service_start_date != service_start:
                    raise ValueError(f"Existing service date differs for {item['business_name']}")

                connection = database.scalar(
                    select(models.WebsiteConnection).where(
                        or_(
                            models.WebsiteConnection.client_id == client.id,
                            models.WebsiteConnection.external_project_id == item["external_project_id"],
                            models.WebsiteConnection.project_name == item["project_name"],
                        )
                    )
                )
                if connection is None:
                    connection = models.WebsiteConnection(
                        client_id=client.id,
                        provider="vercel",
                        external_project_id=item["external_project_id"],
                        project_name=item["project_name"],
                        production_url=item["production_url"],
                        source="confirmed_vercel_import",
                    )
                    database.add(connection)
                elif (
                    connection.client_id != client.id
                    or connection.external_project_id != item["external_project_id"]
                    or connection.production_url != item["production_url"]
                ):
                    raise ValueError(f"Existing website link differs for {item['business_name']}")
                else:
                    connection.source = "confirmed_vercel_import"

                imported.append((client.id, item["business_name"], item["production_url"]))

            if dry_run:
                database.rollback()
            else:
                database.commit()
        except Exception:
            database.rollback()
            raise

    return imported


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Import confirmed Vercel client links safely")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate and simulate the import without saving database changes",
    )
    arguments = parser.parse_args()
    imported_records = import_clients(dry_run=arguments.dry_run)
    action = "Would import" if arguments.dry_run else "Imported"
    print(f"{action} {len(imported_records)} client website link(s)")
    for client_id, business_name, production_url in imported_records:
        print(f"{client_id}\t{business_name}\t{production_url}")
