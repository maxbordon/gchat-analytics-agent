"""Renders Vega-Lite specs to PNG and publishes them where Chat can load them."""
from __future__ import annotations

import logging
import secrets
from datetime import timedelta
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)

# A rendered chart with data is rarely this small; smaller usually means empty.
SUSPICIOUSLY_SMALL_PNG_BYTES = 30_000


def render_png(spec: dict, scale: int = 2) -> bytes:
    import vl_convert as vlc  # lazy: heavy native dependency

    png = vlc.vegalite_to_png(vl_spec=spec, scale=scale)
    if len(png) < SUSPICIOUSLY_SMALL_PNG_BYTES:
        values = (spec.get("data") or {}).get("values")
        logger.warning("Chart PNG is only %d bytes (rows in spec: %s) - may be empty",
                       len(png), len(values) if isinstance(values, list) else "n/a")
    return png


class ChartPublisher(Protocol):
    def publish(self, spec: dict) -> str: ...


class GcsChartPublisher:
    """Uploads to a private bucket and returns a time-limited V4 signed URL."""

    def __init__(self, bucket: str, ttl_days: int = 5):
        if not bucket:
            raise ValueError("CHARTS_BUCKET is required to publish charts")
        self.bucket_name = bucket
        self.ttl_days = ttl_days
        self._client = None

    def _bucket(self):
        if self._client is None:
            from google.cloud import storage
            self._client = storage.Client()
        return self._client.bucket(self.bucket_name)

    def publish(self, spec: dict) -> str:
        import google.auth
        import google.auth.transport.requests

        blob = self._bucket().blob(f"charts/{secrets.token_urlsafe(16)}.png")
        blob.upload_from_string(render_png(spec), content_type="image/png")

        # Signing via the IAM API (no key file): the SA needs TokenCreator on itself.
        creds, _ = google.auth.default()
        creds.refresh(google.auth.transport.requests.Request())
        return blob.generate_signed_url(
            version="v4",
            expiration=timedelta(days=self.ttl_days),
            method="GET",
            service_account_email=creds.service_account_email,
            access_token=creds.token,
        )


class LocalChartPublisher:
    """Mock mode: writes PNGs to a local folder (or skips if vl-convert is missing)."""

    def __init__(self, out_dir: str | Path = "out/charts"):
        self.out_dir = Path(out_dir)

    def publish(self, spec: dict) -> str:
        try:
            png = render_png(spec)
        except ImportError:
            logger.info("vl-convert-python not installed; skipping chart render")
            return "https://example.com/chart-not-rendered.png"
        self.out_dir.mkdir(parents=True, exist_ok=True)
        path = self.out_dir / f"{secrets.token_urlsafe(8)}.png"
        path.write_bytes(png)
        return path.resolve().as_uri()
