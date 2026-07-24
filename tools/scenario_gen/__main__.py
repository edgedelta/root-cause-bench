import sys
from pathlib import Path

from .emit import emit_scenario

if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python -m tools.scenario_gen <path/to/scenario.toml>")
    out = emit_scenario(Path(sys.argv[1]))
    data = out / "environment" / "data"
    total = sum(p.stat().st_size for p in data.rglob("*") if p.is_file())
    print(f"emitted {out}  (data: {total:,} bytes)")
