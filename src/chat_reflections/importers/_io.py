import json
import zipfile
from datetime import UTC, datetime
from fnmatch import fnmatch
from pathlib import Path
from typing import Any


def load_json(path: Path, member_pattern: str) -> Any:
    """Load JSON from a plain file or from the first zip member matching the pattern."""
    if path.suffix != ".zip":
        return json.loads(path.read_text(encoding="utf-8"))
    with zipfile.ZipFile(path) as zf:
        for name in zf.namelist():
            if fnmatch(Path(name).name, member_pattern):
                return json.loads(zf.read(name))
    raise FileNotFoundError(f"no member matching {member_pattern!r} in {path}")


def load_json_all(path: Path, member_pattern: str) -> list[Any]:
    """Load every zip member matching the pattern (sharded exports), or the plain file."""
    if path.suffix != ".zip":
        return [json.loads(path.read_text(encoding="utf-8"))]
    with zipfile.ZipFile(path) as zf:
        names = sorted(n for n in zf.namelist() if fnmatch(Path(n).name, member_pattern))
        return [json.loads(zf.read(n)) for n in names]


def image_part(archive: Path, member: str, name: str) -> dict[str, str]:
    """Message part pointing at an image inside an export zip; served by /api/image, not indexed.
    The archive path is kept relative to the working directory when possible, so an index built on
    the host also works in the container (both run from the project root)."""
    path = archive.resolve()
    if path.is_relative_to(Path.cwd()):
        path = path.relative_to(Path.cwd())
    return {"type": "image", "archive": str(path), "member": member, "name": name}


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def from_epoch(value: float) -> datetime:
    return datetime.fromtimestamp(value, tz=UTC)
