from datetime import date
from unittest.mock import MagicMock

from src.extractors.base import bronze_key, write_bronze


def test_bronze_key_is_date_partitioned():
    assert bronze_key("nse_bhavcopy", date(2026, 10, 7), "f.csv") == "nse_bhavcopy/dt=2026-10-07/f.csv"


def test_write_bronze_is_idempotent_same_key():
    c = MagicMock()
    k1 = write_bronze("amfi_navall", date(2026, 10, 7), "NAVAll.txt", b"x", c)
    k2 = write_bronze("amfi_navall", date(2026, 10, 7), "NAVAll.txt", b"x", c)
    assert k1 == k2
