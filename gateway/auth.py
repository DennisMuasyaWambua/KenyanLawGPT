"""Authentication helpers: local token auth + Google Sign-In verification.

We reuse DRF's ``authtoken`` for our own session tokens (issued on sign-up /
sign-in) and verify Google ID tokens out-of-band. Google verification goes
through :func:`verify_google_id_token`, which is intentionally a single seam so
tests can patch it without hitting the network.
"""
import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

GOOGLE_TOKENINFO_URL = 'https://oauth2.googleapis.com/tokeninfo'


class GoogleAuthError(Exception):
    """Raised when a Google ID token can't be verified."""


def verify_google_id_token(id_token):
    """Verify a Google ID token and return its claims.

    Returns a dict with at least ``email``, ``email_verified``, ``sub`` and
    ``name``. Raises :class:`GoogleAuthError` on any problem.

    Verification hits Google's ``tokeninfo`` endpoint (no extra dependency).
    The audience is checked against ``GOOGLE_OAUTH_CLIENT_ID`` when that setting
    is configured; in development it may be left unset.
    """
    if not id_token:
        raise GoogleAuthError('Missing Google credential.')

    try:
        resp = requests.get(
            GOOGLE_TOKENINFO_URL, params={'id_token': id_token}, timeout=8
        )
    except requests.RequestException as exc:  # pragma: no cover - network
        raise GoogleAuthError(f'Could not reach Google: {exc}') from exc

    if resp.status_code != 200:
        raise GoogleAuthError('Google rejected the credential.')

    claims = resp.json()

    expected_aud = getattr(settings, 'GOOGLE_OAUTH_CLIENT_ID', '') or ''
    if expected_aud and claims.get('aud') != expected_aud:
        raise GoogleAuthError('Google credential was issued for another app.')

    if not claims.get('email'):
        raise GoogleAuthError('Google credential has no email.')

    # tokeninfo returns email_verified as the string "true"/"false".
    verified = claims.get('email_verified')
    claims['email_verified'] = verified in (True, 'true', 'True')
    return claims
