"""Shared HTTP session (retries, rate limit) and Bronze (MinIO/S3) writer."""
import os
import time
import logging
from datetime import date

import boto3
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger("extractors")

NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}


class NotAvailable(Exception):
    """File does not exist for that date (holiday / not yet published)."""


def make_session(min_interval: float = 1.0) -> requests.Session:
    s = requests.Session()
    retry = Retry(total=4, backoff_factor=2, status_forcelist=(429, 500, 502, 503, 504))
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.headers.update(NSE_HEADERS)
    s._min_interval = min_interval
    s._last = 0.0
    return s


def polite_get(session: requests.Session, url: str, **kw) -> requests.Response:
    wait = session._min_interval - (time.time() - session._last)
    if wait > 0:
        time.sleep(wait)
    resp = session.get(url, timeout=30, **kw)
    session._last = time.time()
    return resp


def bronze_client():
    return boto3.client(
        "s3",
        endpoint_url=os.getenv("MINIO_ENDPOINT", "http://localhost:9000"),
        aws_access_key_id=os.getenv("MINIO_ROOT_USER", "minioadmin"),
        aws_secret_access_key=os.getenv("MINIO_ROOT_PASSWORD", "minioadmin"),
    )


def bronze_key(source: str, d: date, filename: str) -> str:
    """Date-partitioned path, e.g. nse_bhavcopy/dt=2026-10-07/file.csv"""
    return f"{source}/dt={d.isoformat()}/{filename}"


def write_bronze(source: str, d: date, filename: str, content: bytes, client=None) -> str:
    """Idempotent: same key is overwritten, so re-running a day never duplicates."""
    client = client or bronze_client()
    key = bronze_key(source, d, filename)
    client.put_object(Bucket="bronze", Key=key, Body=content)
    log.info("wrote s3://bronze/%s (%d bytes)", key, len(content))
    return key
