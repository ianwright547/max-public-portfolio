# Production database backups

Max does not silently create or delete backup files. An operator or scheduled
infrastructure job must provide an explicit destination and retain artifacts in
the organization's encrypted backup storage.

Create and verify one PostgreSQL custom-format backup:

```sh
python scripts/backup_database.py \
  --output /secure/backups/max-$(date -u +%Y%m%dT%H%M%SZ).dump
```

The command:

- refuses SQLite and refuses to overwrite an existing file unless `--force` is
  explicitly supplied;
- never prints `MAX_DATABASE_URL` or command stderr, which may contain provider
  details;
- runs `pg_dump --format=custom --no-owner --no-privileges`;
- runs `pg_restore --list` against the artifact as a read-only structural check;
- restricts the resulting file to owner read/write (`0600`); and
- prints only the path, byte count, and SHA-256 checksum.

Run a read-only freshness/integrity gate from the backup monitor or deployment
health job:

```sh
python scripts/check_backup_age.py \
  --path /secure/backups/max-latest.dump \
  --max-age-hours 26 \
  --sha256 EXPECTED_HEX_CHECKSUM
```

The check fails if the artifact is missing, empty, stale, group/world readable
or writable, modified in the future, or has a checksum mismatch. It does not
modify the artifact or database.

Run the required isolated restore rehearsal with a separate PostgreSQL target:

```sh
python scripts/restore_database_rehearsal.py \
  --backup /secure/backups/max-latest.dump \
  --target-url postgresql://restore_user:password@restore-db/max_restore \
  --confirm-isolated-target
```

The command refuses to run without the explicit confirmation flag, rejects a
target with the same host/port/database identity as `MAX_DATABASE_URL`, restores
with `pg_restore`, and then runs a read-only `SELECT 1` against the target. It
never prints either database URL.

Release operations must additionally:

1. Store the artifact outside the application filesystem, with encryption and a
   retention policy appropriate for client data.
2. Run a restore rehearsal against an isolated PostgreSQL database before the
   first paid client goes live and after material schema changes.
3. Monitor backup age and verification exit status; a missing or unverifiable
   latest backup is a release blocker.
4. Keep the last known-good application commit and migration revision alongside
   the backup metadata so rollback can reproduce the schema expected by the
   application.
