import pytest

from ibkr_mcp.core.safety.killswitch import KillSwitch, KillSwitchEngaged


def test_not_engaged_by_default(tmp_path):
    ks = KillSwitch(path=tmp_path / "KILL")
    assert ks.is_engaged() is False
    ks.check()  # must not raise


def test_engaged_when_file_present(tmp_path):
    p = tmp_path / "KILL"
    ks = KillSwitch(path=p)
    p.write_text("frozen")  # simulates `touch ~/.ibkr-mcp/KILL`
    assert ks.is_engaged() is True
    with pytest.raises(KillSwitchEngaged):
        ks.check()


def test_engaged_when_runtime_armed(tmp_path):
    ks = KillSwitch(path=tmp_path / "KILL")
    ks.arm("manual stop")
    assert ks.is_engaged() is True
    with pytest.raises(KillSwitchEngaged):
        ks.check()
    ks.disarm()
    assert ks.is_engaged() is False


def test_check_message_includes_reason(tmp_path):
    ks = KillSwitch(path=tmp_path / "KILL")
    ks.arm("circuit breaker")
    with pytest.raises(KillSwitchEngaged, match="circuit breaker"):
        ks.check()


def test_check_message_includes_sentinel_path(tmp_path):
    p = tmp_path / "KILL"
    p.write_text("frozen")
    ks = KillSwitch(path=p)
    with pytest.raises(KillSwitchEngaged, match="sentinel file"):
        ks.check()
