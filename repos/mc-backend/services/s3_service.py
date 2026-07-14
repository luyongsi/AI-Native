"""MC Backend — S3 Prototype Storage Service.

Handles prototype HTML upload to S3-compatible storage.
Falls back to inline Base64 storage when S3 is unavailable.
"""

import base64
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# S3-compatible storage config (MinIO/AWS S3)
S3_ENDPOINT = os.environ.get("S3_ENDPOINT", "http://localhost:9000")
S3_ACCESS_KEY = os.environ.get("S3_ACCESS_KEY", "minioadmin")
S3_SECRET_KEY = os.environ.get("S3_SECRET_KEY", "minioadmin")
S3_BUCKET = os.environ.get("S3_BUCKET", "ai-native-prototypes")
S3_BASE_URL = os.environ.get("S3_BASE_URL", "http://localhost:9000/ai-native-prototypes")
S3_REGION = os.environ.get("S3_REGION", "us-east-1")


class S3PrototypeStorage:
    """S3-compatible prototype file storage with graceful degradation."""

    def __init__(self):
        self._client = None
        self._available = None  # lazily determined

    async def _ensure_client(self) -> bool:
        """Lazily initialize S3 client. Returns True if available."""
        if self._available is not None:
            return self._available

        try:
            import aioboto3

            session = aioboto3.Session()
            self._client = await session.client(
                "s3",
                endpoint_url=S3_ENDPOINT,
                aws_access_key_id=S3_ACCESS_KEY,
                aws_secret_access_key=S3_SECRET_KEY,
                region_name=S3_REGION,
            ).__aenter__()

            # Verify bucket exists
            try:
                await self._client.head_bucket(Bucket=S3_BUCKET)
            except Exception:
                await self._client.create_bucket(Bucket=S3_BUCKET)
                logger.info(f"Created S3 bucket: {S3_BUCKET}")

            self._available = True
            logger.info(f"S3 storage available at {S3_ENDPOINT}/{S3_BUCKET}")
            return True
        except ImportError:
            logger.warning("aioboto3 not installed, S3 unavailable")
            self._available = False
            return False
        except Exception as e:
            logger.warning(f"S3 storage unavailable: {e}")
            self._available = False
            return False

    async def upload_html(
        self, req_id: str, version: int, html: str,
    ) -> tuple[Optional[str], Optional[str]]:
        """Upload HTML to S3. Returns (url, base64) tuple.

        On success: (url, None). On failure: (None, base64_string).
        """
        if not await self._ensure_client():
            b64 = base64.b64encode(html.encode()).decode()
            return None, b64

        key = f"prototypes/{req_id}/v{version}.html"
        try:
            await self._client.put_object(
                Bucket=S3_BUCKET,
                Key=key,
                Body=html.encode(),
                ContentType="text/html; charset=utf-8",
            )
            url = f"{S3_BASE_URL}/{key}"
            logger.info(f"Uploaded prototype HTML: {url}")
            return url, None
        except Exception as e:
            logger.warning(f"S3 upload failed for {key}: {e}, falling back to Base64")
            b64 = base64.b64encode(html.encode()).decode()
            return None, b64

    async def upload_screenshot(
        self, req_id: str, version: int, state: str, png_bytes: bytes,
    ) -> Optional[str]:
        """Upload a screenshot PNG to S3. Returns URL or None on failure."""
        if not await self._ensure_client():
            return None

        key = f"prototypes/{req_id}/v{version}/screens/{state}.png"
        try:
            await self._client.put_object(
                Bucket=S3_BUCKET,
                Key=key,
                Body=png_bytes,
                ContentType="image/png",
            )
            url = f"{S3_BASE_URL}/{key}"
            logger.info(f"Uploaded screenshot: {url}")
            return url
        except Exception as e:
            logger.warning(f"S3 screenshot upload failed: {e}")
            return None

    async def get_html(self, req_id: str, version: int) -> Optional[str]:
        """Download HTML from S3."""
        if not await self._ensure_client():
            return None

        key = f"prototypes/{req_id}/v{version}.html"
        try:
            resp = await self._client.get_object(Bucket=S3_BUCKET, Key=key)
            async with resp["Body"] as stream:
                return await stream.read()
        except Exception as e:
            logger.warning(f"S3 download failed for {key}: {e}")
            return None

    async def close(self):
        """Close the S3 client."""
        if self._client:
            try:
                await self._client.__aexit__(None, None, None)
            except Exception:
                pass


# Singleton
_s3_storage: Optional[S3PrototypeStorage] = None


def get_s3_storage() -> S3PrototypeStorage:
    """Get or create the singleton S3 storage instance."""
    global _s3_storage
    if _s3_storage is None:
        _s3_storage = S3PrototypeStorage()
    return _s3_storage
