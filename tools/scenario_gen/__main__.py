import sys
from pathlib import Path

from .emit import emit_scenario
from .spec import SpecError


def main(argv: list[str] | None = None) -> None:
    if argv is None:
        argv = sys.argv[1:]
    if len(argv) != 1:
        sys.exit("usage: python -m tools.scenario_gen <path/to/scenario.toml>")
    try:
        out = emit_scenario(Path(argv[0]))
    except SpecError as e:
        sys.exit(f"spec error: {e}")
    data = out / "environment" / "data"
    total = sum(p.stat().st_size for p in data.rglob("*") if p.is_file())
    print(f"emitted {out}  (data: {total:,} bytes)")


if __name__ == "__main__":
    main()
