"""Object storage + presigned uploads.

Two backends, chosen by configuration:

* **S3-compatible** (when ``AWS_STORAGE_BUCKET_NAME`` is set and ``boto3`` is
  installed): issues a real presigned ``PUT`` URL. Works with AWS S3, MinIO,
  Cloudflare R2, etc.
* **Local dev** (default): returns a URL back to our own signed upload endpoint
  so the presign UI works end-to-end without any cloud account.

The browser flow is identical in both cases: ``POST /api/uploads/presign`` →
``PUT`` the bytes to ``upload_url`` → tell the API the object is ready.
"""
import os
import uuid
from pathlib import Path

from django.conf import settings
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner

_LOCAL_UPLOAD_TTL = 60 * 30  # signed local upload URLs are valid 30 minutes
_signer = TimestampSigner(salt='gateway.local-upload')


def _s3_enabled():
    return bool(getattr(settings, 'AWS_STORAGE_BUCKET_NAME', '') or '')


def generate_storage_key(prefix, firm_id, filename):
    """A collision-free object key namespaced by firm and a random segment."""
    safe = os.path.basename(filename or 'file').replace('/', '_')
    return f'{prefix}/{firm_id}/{uuid.uuid4().hex}/{safe}'


def _s3_client():
    import boto3  # imported lazily; only needed when S3 is configured
    from botocore.config import Config

    # SigV4 + path-style addressing are required for reliable Cloudflare R2
    # presigned URLs (keeps them as endpoint/bucket/key, matching R2's CORS
    # model); both are also valid for AWS S3 and MinIO.
    return boto3.client(
        's3',
        endpoint_url=getattr(settings, 'AWS_S3_ENDPOINT_URL', None) or None,
        region_name=getattr(settings, 'AWS_S3_REGION_NAME', None) or None,
        aws_access_key_id=getattr(settings, 'AWS_ACCESS_KEY_ID', None) or None,
        aws_secret_access_key=getattr(settings, 'AWS_SECRET_ACCESS_KEY', None) or None,
        config=Config(signature_version='s3v4', s3={'addressing_style': 'path'}),
    )


def create_presigned_upload(key, content_type=''):
    """Return the instructions the client needs to upload one object.

    Shape: ``{"storage": ..., "key": ..., "upload_url": ..., "method": "PUT",
    "headers": {...}}``.
    """
    if _s3_enabled():
        client = _s3_client()
        params = {'Bucket': settings.AWS_STORAGE_BUCKET_NAME, 'Key': key}
        if content_type:
            params['ContentType'] = content_type
        url = client.generate_presigned_url(
            'put_object', Params=params, ExpiresIn=_LOCAL_UPLOAD_TTL
        )
        headers = {'Content-Type': content_type} if content_type else {}
        return {
            'storage': 's3',
            'key': key,
            'upload_url': url,
            'method': 'PUT',
            'headers': headers,
        }

    # Local dev backend: hand back a signed URL to our own PUT endpoint.
    token = _signer.sign(key)
    base = getattr(settings, 'PUBLIC_BASE_URL', '').rstrip('/')
    path = f'/api/uploads/local/{token}'
    return {
        'storage': 'local',
        'key': key,
        'upload_url': f'{base}{path}' if base else path,
        'method': 'PUT',
        'headers': {'Content-Type': content_type} if content_type else {},
    }


def _local_root():
    root = getattr(settings, 'MEDIA_ROOT', None) or (Path(settings.BASE_DIR) / 'media')
    return Path(root)


def local_path_for_key(key):
    return _local_root() / key


def verify_local_token(token):
    """Return the storage key for a signed local-upload token, or raise."""
    try:
        return _signer.unsign(token, max_age=_LOCAL_UPLOAD_TTL)
    except SignatureExpired as exc:
        raise ValueError('Upload link has expired.') from exc
    except BadSignature as exc:
        raise ValueError('Invalid upload link.') from exc


def save_local_object(key, data):
    path = local_path_for_key(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'wb') as fh:
        fh.write(data)
    return path


def read_object(key):
    """Read an object's bytes back (used by ingestion / transcription)."""
    if _s3_enabled():
        client = _s3_client()
        obj = client.get_object(Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=key)
        return obj['Body'].read()
    path = local_path_for_key(key)
    with open(path, 'rb') as fh:
        return fh.read()
