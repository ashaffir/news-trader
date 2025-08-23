import os
from pathlib import Path
from datetime import datetime, timedelta
from typing import Iterable, Optional, Union, Dict, List


def _iter_matching_files(directory: Path, patterns: Iterable[str]) -> Iterable[Path]:
    for pattern in patterns:
        yield from directory.glob(pattern)


def cleanup_logs(
    log_dir: Union[str, Path],
    max_age_days: int,
    patterns: Optional[List[str]] = None,
) -> Dict[str, object]:
    """Delete log files older than ``max_age_days`` in ``log_dir``.

    Args:
        log_dir: Directory containing log files.
        max_age_days: Files older than this age will be deleted.
        patterns: Filename glob patterns to consider. Defaults to common log patterns.

    Returns:
        Dict with statistics: total_scanned, deleted_count, kept_count, deleted_files
    """
    directory = Path(log_dir)
    directory.mkdir(exist_ok=True, parents=True)

    if patterns is None:
        patterns = [
            "*.log",
            "*.log.*",
            "*.out",
            "*.err",
        ]

    cutoff = datetime.utcnow() - timedelta(days=int(max_age_days))

    total_scanned = 0
    deleted_files: List[str] = []
    kept_count = 0

    for file_path in _iter_matching_files(directory, patterns):
        if not file_path.is_file():
            continue
        # never touch sentinel files
        if file_path.name in {".gitkeep", ".keep"}:
            continue
        total_scanned += 1

        try:
            mtime = datetime.utcfromtimestamp(file_path.stat().st_mtime)
            if mtime < cutoff:
                try:
                    file_path.unlink(missing_ok=True)
                    deleted_files.append(str(file_path))
                except Exception:
                    kept_count += 1
            else:
                kept_count += 1
        except Exception:
            kept_count += 1

    return {
        "total_scanned": total_scanned,
        "deleted_count": len(deleted_files),
        "kept_count": kept_count,
        "deleted_files": deleted_files,
    }


