import pytest
from unittest.mock import MagicMock
import os


@pytest.fixture
def mock_udev(monkeypatch):
    """Fixture to mock os.stat and pyudev for device lookup."""
    os_stat_orig = os.stat

    def mock_os_stat(p):
        if str(p).startswith("/dev/"):
            m = MagicMock()
            m.st_rdev = 1234
            return m
        return os_stat_orig(p)

    monkeypatch.setattr(os, "stat", mock_os_stat)

    mock_context = MagicMock()
    mock_device = MagicMock()
    # Default behavior: return "MY_LABEL" for ID_FS_LABEL and a valid size
    mock_device.get.side_effect = lambda k: "MY_LABEL" if k == "ID_FS_LABEL" else None
    mock_device.attributes = MagicMock()
    mock_device.attributes.get.return_value = "2097152"  # 1GiB in 512b sectors

    monkeypatch.setattr("pyudev.Context", lambda: mock_context)
    from_dev_num = MagicMock(return_value=mock_device)
    monkeypatch.setattr("pyudev.Devices.from_device_number", from_dev_num)

    return {
        "context": mock_context,
        "device": mock_device,
        "from_device_number": from_dev_num,
    }
