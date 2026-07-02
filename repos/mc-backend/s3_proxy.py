"""
Mission Control Backend - S3 Pre-signed URL Proxy
Development mode: returns mock URLs or local paths.
"""
import os

S3_BUCKET = os.environ.get("S3_BUCKET", "ai-native-artifacts")
S3_ENDPOINT = os.environ.get("S3_ENDPOINT", "http://localhost:9000")
DEV_MODE = os.environ.get("DEV_MODE", "true").lower() in ("1", "true", "yes")


def get_presigned_url(key: str, expires_in: int = 3600) -> str:
    """Return a pre-signed URL for the given S3 object key.
    In development mode, returns a mock URL.
    """
    if DEV_MODE:
        return f"http://localhost:9000/{S3_BUCKET}/{key}?mock-presigned=true&expires={expires_in}"

    # Production: use boto3 to generate real pre-signed URL
    try:
        import boto3
        from botocore.client import Config
        s3 = boto3.client(
            "s3",
            endpoint_url=S3_ENDPOINT,
            config=Config(signature_version="s3v4"),
        )
        url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": S3_BUCKET, "Key": key},
            ExpiresIn=expires_in,
        )
        return url
    except Exception:
        return f"http://localhost:9000/{S3_BUCKET}/{key}?mock-presigned=true&expires={expires_in}"


def get_upload_url(key: str, expires_in: int = 3600) -> str:
    """Return a pre-signed upload URL."""
    if DEV_MODE:
        return f"http://localhost:9000/{S3_BUCKET}/{key}?mock-upload=true&expires={expires_in}"

    try:
        import boto3
        from botocore.client import Config
        s3 = boto3.client(
            "s3",
            endpoint_url=S3_ENDPOINT,
            config=Config(signature_version="s3v4"),
        )
        url = s3.generate_presigned_url(
            "put_object",
            Params={"Bucket": S3_BUCKET, "Key": key},
            ExpiresIn=expires_in,
        )
        return url
    except Exception:
        return f"http://localhost:9000/{S3_BUCKET}/{key}?mock-upload=true&expires={expires_in}"
