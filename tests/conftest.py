"""Keep automated test records out of the real Max database."""

import os


os.environ["MAX_DATABASE_URL"] = f"sqlite:////tmp/max_pytest_{os.getpid()}.db"
# The broad API suite exercises application behavior without an owner session.
# Authentication-specific tests explicitly enable it with monkeypatch.
os.environ["MAX_REQUIRE_AUTH"] = "false"
os.environ["AUTH_SECRET"] = ""
os.environ["CRON_SECRET"] = ""
os.environ["VERCEL_API_TOKEN"] = ""

# A fresh portfolio checkout has no local database. Build the schema directly
# for tests so reviewers can run the suite without importing a production DB.
from app.database import Base, engine

Base.metadata.create_all(bind=engine)
