"""Multilingual speech-to-text via the IE transcription API.

The IE model is reached with a bearer API key (a JWT) configured out of band
as ``IE_API_KEY`` — never hardcode it in the repo. The endpoint URL is
``IE_TRANSCRIPTION_URL``.

:func:`transcribe_audio` is the single seam the rest of the app depends on, so
tests patch it directly and never touch the network. It returns a normalised
dict: ``{"text", "language", "segments", "provider"}``.
"""
import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class TranscriptionError(Exception):
    pass


def _normalise(payload):
    """Coerce a provider response into our transcript shape.

    We accept a few common field spellings because the exact IE response schema
    is configured per deployment; anything we can't find degrades to empty.
    """
    if not isinstance(payload, dict):
        return {'text': str(payload), 'language': '', 'segments': [], 'provider': 'ie'}

    text = (
        payload.get('text')
        or payload.get('transcript')
        or payload.get('transcription')
        or ''
    )
    language = (
        payload.get('language')
        or payload.get('detected_language')
        or payload.get('lang')
        or ''
    )
    segments = payload.get('segments') or payload.get('results') or []
    return {
        'text': text,
        'language': language,
        'segments': segments if isinstance(segments, list) else [],
        'provider': 'ie',
    }


def transcribe_audio(data, filename='audio', content_type='application/octet-stream',
                     language=''):
    """Send audio bytes to the IE transcription API and return the transcript.

    ``language`` may be an ISO code or left blank to let the multilingual model
    auto-detect. Raises :class:`TranscriptionError` on any failure.
    """
    url = getattr(settings, 'IE_TRANSCRIPTION_URL', '') or ''
    api_key = getattr(settings, 'IE_API_KEY', '') or ''
    if not url or not api_key:
        raise TranscriptionError(
            'Transcription is not configured (set IE_TRANSCRIPTION_URL and IE_API_KEY).'
        )

    files = {'file': (filename, data, content_type or 'application/octet-stream')}
    form = {'multilingual': 'true'}
    if language:
        form['language'] = language

    try:
        resp = requests.post(
            url,
            headers={'Authorization': f'Bearer {api_key}'},
            files=files,
            data=form,
            timeout=getattr(settings, 'IE_TRANSCRIPTION_TIMEOUT', 300),
        )
    except requests.RequestException as exc:  # pragma: no cover - network
        raise TranscriptionError(f'Could not reach the transcription service: {exc}') from exc

    if resp.status_code != 200:
        raise TranscriptionError(
            f'Transcription service returned HTTP {resp.status_code}: {resp.text[:200]}'
        )

    try:
        payload = resp.json()
    except ValueError:
        payload = {'text': resp.text}
    return _normalise(payload)
