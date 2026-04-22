import pytest
from unittest.mock import patch, mock_open, MagicMock
from src.health import PiHealthMonitor

@pytest.fixture
def linux_monitor():
    with patch("platform.system", return_value="Linux"):
        yield PiHealthMonitor()

@pytest.fixture
def mac_monitor():
    with patch("platform.system", return_value="Darwin"):
        yield PiHealthMonitor()

@pytest.mark.unit
def test_fallback_mac(mac_monitor):
    assert mac_monitor.get_temperature() == 45.0
    mem = mac_monitor.get_memory_usage()
    assert mem["total_mb"] == 8192.0
    assert mac_monitor.get_cpu_usage() == 20.0
    assert mac_monitor.is_throttled() is False

@pytest.mark.unit
@patch("os.path.exists", return_value=True)
def test_temp_sysfs(mock_exists, linux_monitor):
    with patch("builtins.open", mock_open(read_data="45123\n")):
        temp = linux_monitor.get_temperature()
        assert temp == 45.123

@pytest.mark.unit
@patch("os.path.exists", return_value=False)
@patch("subprocess.run")
def test_temp_vcgencmd(mock_run, mock_exists, linux_monitor):
    mock_result = MagicMock()
    mock_result.stdout = "temp=52.5'C\n"
    mock_run.return_value = mock_result
    
    temp = linux_monitor.get_temperature()
    assert temp == 52.5
    mock_run.assert_called_with(["vcgencmd", "measure_temp"], capture_output=True, text=True, check=True)

@pytest.mark.unit
def test_memory_usage(linux_monitor):
    meminfo_data = (
        "MemTotal:        8192000 kB\n"
        "MemFree:         1024000 kB\n"
        "MemAvailable:    4096000 kB\n"
    )
    with patch("builtins.open", mock_open(read_data=meminfo_data)):
        mem = linux_monitor.get_memory_usage()
        assert mem["total_mb"] == 8000.0  # 8192000 / 1024
        assert mem["available_mb"] == 4000.0 # 4096000 / 1024
        assert mem["percent"] == 50.0  # (8000 - 4000) / 8000 * 100

@pytest.mark.unit
def test_is_throttled(linux_monitor):
    with patch("subprocess.run") as mock_run:
        # 0x0 -> not throttled
        mock_result = MagicMock()
        mock_result.stdout = "throttled=0x0\n"
        mock_run.return_value = mock_result
        assert linux_monitor.is_throttled() is False

        # 0x2 -> currently throttled (frequency capped)
        mock_result.stdout = "throttled=0x2\n"
        mock_run.return_value = mock_result
        assert linux_monitor.is_throttled() is True

        # 0x50005 -> under-voltage occurred and currently under-voltage (bit 0 and bit 2 are 1, bit 16 and 18 are 1)
        # bit 2 is 0x4 (currently throttled), so it should return True
        mock_result.stdout = "throttled=0x50005\n"
        mock_run.return_value = mock_result
        assert linux_monitor.is_throttled() is True

@pytest.mark.unit
@patch("time.sleep", return_value=None)
def test_cpu_usage(mock_sleep, linux_monitor):
    # Mocking multiple open calls for /proc/stat
    # Format: cpu  user nice system idle iowait irq softirq steal guest guest_nice
    data1 = "cpu  1000 0 1000 8000 0 0 0 0 0 0\n" # total: 10000, idle: 8000
    data2 = "cpu  1100 0 1100 8300 0 0 0 0 0 0\n" # total: 10500 (+500), idle: 8300 (+300) => usage = (500-300)/500 = 40%
    
    mock_file = mock_open(read_data=data1)
    mock_file.side_effect = [
        mock_open(read_data=data1).return_value,
        mock_open(read_data=data2).return_value
    ]
    
    with patch("builtins.open", mock_file):
        pct = linux_monitor.get_cpu_usage()
        assert pct == 40.0
