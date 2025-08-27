import os
import shutil
import subprocess
import datetime
from pathlib import Path
from django.conf import settings


def get_database_connection_settings():
    db = settings.DATABASES.get("default", {})
    return {
        "NAME": db.get("NAME"),
        "USER": db.get("USER"),
        "PASSWORD": db.get("PASSWORD"),
        "HOST": db.get("HOST", "localhost"),
        "PORT": str(db.get("PORT", "5432")),
    }


def ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def build_backup_filename(prefix: str = "news_trader_backup", ext: str = ".sql.gz") -> str:
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{prefix}_{timestamp}{ext}"


def get_default_backup_dir() -> Path:
    # Local machine (not docker): default to project_root/backups
    root = Path(settings.BASE_DIR)
    return root / "backups"


def _resolve_pg_dump_path() -> str:
    # Prefer explicit path via env; fallback to PATH lookup
    explicit = os.environ.get("PG_DUMP_PATH")
    if explicit and Path(explicit).exists():
        return explicit
    resolved = shutil.which("pg_dump")
    if not resolved:
        raise FileNotFoundError("pg_dump not found. Install PostgreSQL client or set PG_DUMP_PATH.")
    return resolved


def run_pg_dump(output_path: Path, db_env: dict) -> None:
    env = os.environ.copy()
    if db_env.get("PASSWORD"):
        env["PGPASSWORD"] = db_env["PASSWORD"]

    pg_dump_bin = _resolve_pg_dump_path()

    # We'll output plain SQL and gzip it ourselves for portability across pg_dump versions
    temp_sql_path = output_path.with_suffix("").with_suffix(".sql")

    cmd = [
        pg_dump_bin,
        "-h",
        db_env.get("HOST", "localhost"),
        "-p",
        db_env.get("PORT", "5432"),
        "-U",
        db_env.get("USER", "postgres"),
        "-d",
        db_env.get("NAME"),
        "-f",
        str(temp_sql_path),
    ]

    subprocess.run(cmd, check=True, env=env)

    # Compress using Python to avoid pg_dump -Z dependency
    import gzip
    with open(temp_sql_path, 'rb') as f_in, gzip.open(output_path, 'wb', compresslevel=9) as f_out:
        shutil.copyfileobj(f_in, f_out)
    try:
        temp_sql_path.unlink(missing_ok=True)
    except Exception:
        pass


def create_database_backup(backup_dir: Path | None = None) -> Path:
    backup_dir = backup_dir or get_default_backup_dir()
    ensure_directory(backup_dir)
    filename = build_backup_filename()
    output_path = backup_dir / filename

    db_env = get_database_connection_settings()
    run_pg_dump(output_path, db_env)

    return output_path



# =============================
# Restore utilities
# =============================

def _resolve_psql_path() -> str:
    explicit = os.environ.get("PSQL_PATH")
    if explicit and Path(explicit).exists():
        return explicit
    resolved = shutil.which("psql")
    if not resolved:
        raise FileNotFoundError("psql not found. Install PostgreSQL client or set PSQL_PATH.")
    return resolved


def list_backup_files(backup_dir: Path | None = None) -> list[Path]:
    backup_dir = backup_dir or get_default_backup_dir()
    if not backup_dir.exists():
        return []
    # Support both .sql and .sql.gz
    files = list(backup_dir.glob("*.sql")) + list(backup_dir.glob("*.sql.gz"))
    return sorted(files)


def find_latest_backup(backup_dir: Path | None = None) -> Path:
    files = list_backup_files(backup_dir)
    if not files:
        raise FileNotFoundError("No backup files found in backups directory")
    # Sort by modified time descending; fall back to name
    files.sort(key=lambda p: (p.stat().st_mtime, p.name))
    return files[-1]


def _run_psql_command(args: list[str], db_env: dict) -> None:
    env = os.environ.copy()
    if db_env.get("PASSWORD"):
        env["PGPASSWORD"] = db_env["PASSWORD"]

    psql_bin = _resolve_psql_path()
    cmd = [psql_bin, "-h", db_env.get("HOST", "localhost"), "-p", db_env.get("PORT", "5432"), "-U", db_env.get("USER", "postgres"), "-d", db_env.get("NAME")] + args
    subprocess.run(cmd, check=True, env=env)


def drop_public_schema(db_env: dict) -> None:
    # Safely drop and recreate public schema to avoid conflicts on restore
    _run_psql_command(["-v", "ON_ERROR_STOP=1", "-c", "DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;"], db_env)


def _decompress_if_needed(backup_path: Path) -> Path:
    if backup_path.suffix == ".gz":
        import gzip
        target_sql = backup_path.with_suffix("")  # remove .gz -> .sql
        with gzip.open(backup_path, 'rb') as f_in, open(target_sql, 'wb') as f_out:
            shutil.copyfileobj(f_in, f_out)
        return target_sql
    return backup_path


def restore_database_from_backup(backup_file: Path) -> None:
    if not backup_file.exists():
        raise FileNotFoundError(f"Backup not found: {backup_file}")

    db_env = get_database_connection_settings()

    # Prepare database by dropping schema
    drop_public_schema(db_env)

    # Decompress if .gz and apply with psql
    sql_file = _decompress_if_needed(backup_file)
    try:
        _run_psql_command(["-v", "ON_ERROR_STOP=1", "-f", str(sql_file)], db_env)
    finally:
        # Clean up temp decompressed file if we created it
        if sql_file != backup_file and sql_file.exists():
            try:
                sql_file.unlink()
            except Exception:
                pass


def restore_latest_backup(backup_dir: Path | None = None) -> Path:
    latest = find_latest_backup(backup_dir)
    restore_database_from_backup(latest)
    return latest

