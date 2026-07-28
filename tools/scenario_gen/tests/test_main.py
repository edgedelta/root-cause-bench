# tools/scenario_gen/tests/test_main.py
import pytest

from tools.scenario_gen.__main__ import main
from tools.scenario_gen.tests.test_emit import FULL
from tools.scenario_gen.tests.test_spec import MINIMAL, write


def test_main_spec_error_exits_cleanly_no_traceback(tmp_path, capsys):
    bad = MINIMAL.replace('family = "beyond-context"', 'family = "whatever"')
    p = write(tmp_path, bad)
    with pytest.raises(SystemExit) as exc_info:
        main([str(p)])
    assert str(exc_info.value).startswith("spec error:")


def test_main_wrong_arg_count_prints_usage():
    with pytest.raises(SystemExit) as exc_info:
        main([])
    assert "usage:" in str(exc_info.value)


def test_main_emits_scenario_and_prints_summary(tmp_path, capsys):
    d = tmp_path / "datasets" / "rootcausebench" / "demo-scenario"
    d.mkdir(parents=True)
    (d / "scenario.toml").write_text(FULL)
    main([str(d / "scenario.toml")])
    out = capsys.readouterr().out
    assert "emitted" in out
    assert (d / "task.toml").exists()
