# Database Migration And Recovery

Siming keeps SQLite as the authority and creates a verified backup before a schema upgrade. Unknown database structures enter read-only recovery mode instead of receiving guessed columns.

## Rehearse Before An RC Upgrade

Close Siming, locate `novel_agent.db`, then run the rehearsal against a disposable copy:

```powershell
backend\.venv\Scripts\python.exe scripts\rehearse_database_migration.py `
  "C:\path\to\novel_agent.db" `
  --working-copy ".build\migration-rehearsal.db" `
  --report ".build\migration-rehearsal.json"
```

Success requires all of the following:

- Source SHA-256 is unchanged.
- Source and migrated copy both pass `PRAGMA integrity_check`.
- Existing project, chapter, character, outline and worldbuilding row counts do not decrease.
- Alembic reaches the expected head revision.

The working copy may contain private novel data. Do not attach it to public issues. The JSON report contains the local source path, so review it before sharing.

## Automatic Backups

Backups are written beside the database under `backups/`. Automatic schema-upgrade and initial-sync snapshots include the reason and UTC timestamp in their names. **Only the latest verified automatic backup is retained for each database.** A successful backup may retire the previous snapshot even when its contents differ. Copy any snapshot you want to archive to a separate location or give it an explicit/manual name.

The SQLite online backup API captures committed WAL data. The destination is checkpointed to a standalone database and must pass `PRAGMA integrity_check` before publication. Only then are older generated upgrade/sync backups and their temporary sidecars removed. Explicit/manual snapshots use a `manual-` name and are outside automatic retention; files for other databases and filesystem links are also excluded.

Backup creation is serialized across processes. It uses one reusable temporary filename, removes failed-attempt sidecars, and checks available space for the copy plus a 32 MiB reserve before writing. An interrupted copy can be cleaned on the next backup attempt. While a new backup is being created, the previous verified copy and the in-progress copy may coexist; a failed copy never replaces the previous recovery backup. Locked historical files are reported and retried on the next successful backup.

Startup verifies the complete migration path before any backup or retired-version normalization. A client that cannot recognize a newer schema enters read-only recovery without copying the database. Updating the configured external MCP command is necessary when it still points to an older installation/source checkout.

Android's independent local database uses Room migrations and does not run this Alembic backup workflow. Gateway-backed mobile operations use the same server backup policy described here.

## Read-Only Recovery

If Siming cannot recognize or migrate the database:

1. Leave the original database untouched.
2. Keep the reported backup and copy it to another disk.
3. Run the rehearsal tool on a copy and preserve its JSON report.
4. Install a repaired release or open an issue with the report after removing private paths.
5. Do not import project mirror files over the database unless you explicitly choose the repair import action.

Restoring a backup should be done only while Siming is fully closed. Keep the failed database under a different filename until the restored copy has opened successfully and project counts have been checked.
