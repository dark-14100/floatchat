"""
FloatChat S3/MinIO Storage Helper

Provides functions to upload, download, and generate presigned URLs for files
stored in S3 or MinIO object storage.

All raw NetCDF files are staged to object storage before parsing begins.
This ensures failed jobs can always be retried from the original file.
"""

from typing import Optional

import boto3
import structlog
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.config import settings

# Module-level logger
logger = structlog.get_logger(__name__)


def get_s3_client():
    """
    Create and return a boto3 S3 client configured from settings.
    
    If S3_ENDPOINT_URL is set, uses it for MinIO compatibility.
    If not set, uses AWS S3 defaults.
    """
    client_config = Config(
        signature_version="s3v4",
        retries={"max_attempts": 3, "mode": "standard"},
    )
    
    client_kwargs = {
        "service_name": "s3",
        "aws_access_key_id": settings.S3_ACCESS_KEY,
        "aws_secret_access_key": settings.S3_SECRET_KEY,
        "region_name": settings.S3_REGION,
        "config": client_config,
    }
    
    # Add endpoint URL for MinIO (local dev) or custom S3-compatible storage
    if settings.S3_ENDPOINT_URL:
        client_kwargs["endpoint_url"] = settings.S3_ENDPOINT_URL
    
    return boto3.client(**client_kwargs)


def upload_file_to_s3(
    local_path: str,
    s3_key: str,
    job_id: Optional[str] = None,
) -> bool:
    """
    Upload a local file to S3/MinIO.
    
    Args:
        local_path: Path to the local file to upload
        s3_key: S3 key (path) where the file will be stored
        job_id: Optional job ID for logging context
    
    Returns:
        True on success
    
    Raises:
        Exception: On upload failure (caller should handle)
    """
    log = logger.bind(job_id=job_id) if job_id else logger
    
    log.info(
        "s3_upload_started",
        local_path=local_path,
        s3_key=s3_key,
        bucket=settings.S3_BUCKET_NAME,
    )
    
    try:
        client = get_s3_client()
        client.upload_file(
            Filename=local_path,
            Bucket=settings.S3_BUCKET_NAME,
            Key=s3_key,
        )
        
        log.info(
            "s3_upload_complete",
            s3_key=s3_key,
            bucket=settings.S3_BUCKET_NAME,
        )
        return True
        
    except (BotoCoreError, ClientError) as e:
        log.error(
            "s3_upload_failed",
            s3_key=s3_key,
            bucket=settings.S3_BUCKET_NAME,
            error=str(e),
        )
        raise


def download_file_from_s3(
    s3_key: str,
    local_path: str,
    job_id: Optional[str] = None,
) -> bool:
    """
    Download a file from S3/MinIO to local filesystem.
    
    Args:
        s3_key: S3 key (path) of the file to download
        local_path: Local path where the file will be saved
        job_id: Optional job ID for logging context
    
    Returns:
        True on success
    
    Raises:
        Exception: On download failure (caller should handle)
    """
    log = logger.bind(job_id=job_id) if job_id else logger
    
    log.info(
        "s3_download_started",
        s3_key=s3_key,
        local_path=local_path,
        bucket=settings.S3_BUCKET_NAME,
    )
    
    try:
        client = get_s3_client()
        client.download_file(
            Bucket=settings.S3_BUCKET_NAME,
            Key=s3_key,
            Filename=local_path,
        )
        
        log.info(
            "s3_download_complete",
            s3_key=s3_key,
            local_path=local_path,
        )
        return True
        
    except (BotoCoreError, ClientError) as e:
        log.error(
            "s3_download_failed",
            s3_key=s3_key,
            error=str(e),
        )
        raise


def generate_presigned_url(
    s3_key: str,
    expires_in: int = 3600,
    job_id: Optional[str] = None,
) -> str:
    """
    Generate a presigned URL for downloading a file from S3/MinIO.
    
    Args:
        s3_key: S3 key (path) of the file
        expires_in: URL expiration time in seconds (default: 1 hour)
        job_id: Optional job ID for logging context
    
    Returns:
        Presigned URL string
    
    Raises:
        Exception: On failure to generate URL
    """
    log = logger.bind(job_id=job_id) if job_id else logger
    
    try:
        client = get_s3_client()
        url = client.generate_presigned_url(
            ClientMethod="get_object",
            Params={
                "Bucket": settings.S3_BUCKET_NAME,
                "Key": s3_key,
            },
            ExpiresIn=expires_in,
        )
        
        log.info(
            "s3_presigned_url_generated",
            s3_key=s3_key,
            expires_in=expires_in,
        )
        return url
        
    except (BotoCoreError, ClientError) as e:
        log.error(
            "s3_presigned_url_failed",
            s3_key=s3_key,
            error=str(e),
        )
        raise


def file_exists_in_s3(s3_key: str) -> bool:
    """
    Check if a file exists in S3/MinIO.
    
    Args:
        s3_key: S3 key (path) of the file
    
    Returns:
        True if file exists, False otherwise
    """
    try:
        client = get_s3_client()
        client.head_object(Bucket=settings.S3_BUCKET_NAME, Key=s3_key)
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "404":
            return False
        raise


def delete_file_from_s3(s3_key: str, job_id: Optional[str] = None) -> bool:
    """
    Delete a file from S3/MinIO.
    
    Args:
        s3_key: S3 key (path) of the file to delete
        job_id: Optional job ID for logging context
    
    Returns:
        True on success
    
    Raises:
        Exception: On deletion failure
    """
    log = logger.bind(job_id=job_id) if job_id else logger
    
    try:
        client = get_s3_client()
        client.delete_object(Bucket=settings.S3_BUCKET_NAME, Key=s3_key)
        
        log.info(
            "s3_file_deleted",
            s3_key=s3_key,
            bucket=settings.S3_BUCKET_NAME,
        )
        return True
        
    except (BotoCoreError, ClientError) as e:
        log.error(
            "s3_delete_failed",
            s3_key=s3_key,
            error=str(e),
        )
        raise
