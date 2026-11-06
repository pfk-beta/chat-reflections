import argparse
from pathlib import Path

from chat_reflections import es
from chat_reflections.importers import IMPORTERS
from chat_reflections.models import Conversation


def iter_source(source: str, raw_dir: Path) -> list[Conversation]:
    importer = IMPORTERS[source]
    files = sorted({p for g in importer.GLOBS for p in (raw_dir / source).glob(g)})
    return [c for f in files for c in importer.parse(f)]


def main() -> None:
    parser = argparse.ArgumentParser(prog="chat-reflections")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("reindex", help="drop indices and import everything from data/raw")
    p.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    args = parser.parse_args()

    if args.cmd == "reindex":
        client = es.client()
        es.recreate_indices(client)
        for source in IMPORTERS:
            convs = iter_source(source, args.raw_dir)
            n = es.index(client, convs)
            print(f"{source}: {len(convs)} conversations, {n} docs")
