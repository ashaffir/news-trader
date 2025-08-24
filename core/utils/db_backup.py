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


