"""Data model for the WakiliAI multi-tenant SaaS gateway.

Everything is scoped to a LawFirm (the tenant). Users are the stock
``django.contrib.auth`` users; their relationship to a firm and their role
inside it live on :class:`Membership`. We deliberately do not swap out
AUTH_USER_MODEL — the deployed database already has the default auth tables,
so we attach tenant data alongside them instead.
"""
import uuid
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.crypto import get_random_string


def _uuid_pk():
    return uuid.uuid4()


class TimestampedModel(models.Model):
    id = models.UUIDField(primary_key=True, default=_uuid_pk, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class LawFirm(TimestampedModel):
    """A tenant. Created during sign-up together with its owner."""

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='owned_firms',
    )

    def __str__(self):
        return self.name


class Membership(TimestampedModel):
    """Links a user to a firm with a role. A user may belong to many firms."""

    ROLE_OWNER = 'owner'
    ROLE_ADMIN = 'admin'
    ROLE_STAFF = 'staff'
    ROLE_CHOICES = [
        (ROLE_OWNER, 'Owner'),
        (ROLE_ADMIN, 'Admin'),
        (ROLE_STAFF, 'Staff'),
    ]

    firm = models.ForeignKey(LawFirm, on_delete=models.CASCADE, related_name='memberships')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='memberships'
    )
    role = models.CharField(max_length=16, choices=ROLE_CHOICES, default=ROLE_STAFF)
    title = models.CharField(max_length=120, blank=True, default='')

    class Meta:
        unique_together = ('firm', 'user')

    @property
    def can_manage(self):
        return self.role in (self.ROLE_OWNER, self.ROLE_ADMIN)

    def __str__(self):
        return f'{self.user} @ {self.firm} ({self.role})'


class Invite(TimestampedModel):
    """A pending staff invitation the firm owner/admin sends by email."""

    STATUS_PENDING = 'pending'
    STATUS_ACCEPTED = 'accepted'
    STATUS_REVOKED = 'revoked'

    firm = models.ForeignKey(LawFirm, on_delete=models.CASCADE, related_name='invites')
    email = models.EmailField()
    role = models.CharField(
        max_length=16, choices=Membership.ROLE_CHOICES, default=Membership.ROLE_STAFF
    )
    title = models.CharField(max_length=120, blank=True, default='')
    token = models.CharField(max_length=64, unique=True, db_index=True)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='sent_invites',
    )
    status = models.CharField(max_length=16, default=STATUS_PENDING)
    expires_at = models.DateTimeField()

    class Meta:
        indexes = [models.Index(fields=['firm', 'email', 'status'])]

    def save(self, *args, **kwargs):
        if not self.token:
            self.token = get_random_string(48)
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(days=14)
        super().save(*args, **kwargs)

    @property
    def is_expired(self):
        return timezone.now() > self.expires_at

    @property
    def is_open(self):
        return self.status == self.STATUS_PENDING and not self.is_expired


class Case(TimestampedModel):
    """A matter the firm is working on; documents are ingested per case."""

    firm = models.ForeignKey(LawFirm, on_delete=models.CASCADE, related_name='cases')
    title = models.CharField(max_length=255)
    reference = models.CharField(max_length=120, blank=True, default='')
    description = models.TextField(blank=True, default='')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='cases'
    )

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.title} ({self.firm})'


class CaseDocument(TimestampedModel):
    """A file attached to a case. Uploaded via presigned URL, then ingested
    into the per-case vector store to ground the AI's legal reasoning."""

    STATUS_PENDING = 'pending'      # presign issued, waiting for the upload
    STATUS_UPLOADED = 'uploaded'    # file is in storage, queued for ingestion
    STATUS_INGESTED = 'ingested'    # text extracted + embedded
    STATUS_FAILED = 'failed'

    case = models.ForeignKey(Case, on_delete=models.CASCADE, related_name='documents')
    filename = models.CharField(max_length=512)
    content_type = models.CharField(max_length=120, blank=True, default='')
    storage_key = models.CharField(max_length=1024)
    size = models.BigIntegerField(null=True, blank=True)
    status = models.CharField(max_length=16, default=STATUS_PENDING)
    chunk_count = models.IntegerField(default=0)
    error = models.TextField(blank=True, default='')
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+'
    )

    class Meta:
        ordering = ['-created_at']


class CalendarEvent(TimestampedModel):
    """A calendar entry. ``is_shared`` distinguishes a firm-wide event from a
    user's personal one. Personal events are only visible to their owner."""

    firm = models.ForeignKey(LawFirm, on_delete=models.CASCADE, related_name='events')
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='events'
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default='')
    location = models.CharField(max_length=255, blank=True, default='')
    start = models.DateTimeField()
    end = models.DateTimeField()
    all_day = models.BooleanField(default=False)
    is_shared = models.BooleanField(default=False)
    case = models.ForeignKey(
        Case, on_delete=models.SET_NULL, null=True, blank=True, related_name='events'
    )
    attendees = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True, related_name='attending_events'
    )

    class Meta:
        ordering = ['start']

    def __str__(self):
        return f'{self.title} @ {self.start:%Y-%m-%d %H:%M}'


class EventReminder(TimestampedModel):
    """A reminder attached to an event, N minutes before it starts."""

    METHOD_APP = 'app'
    METHOD_EMAIL = 'email'
    METHOD_CHOICES = [(METHOD_APP, 'In-app'), (METHOD_EMAIL, 'Email')]

    event = models.ForeignKey(
        CalendarEvent, on_delete=models.CASCADE, related_name='reminders'
    )
    minutes_before = models.PositiveIntegerField(default=30)
    method = models.CharField(max_length=16, choices=METHOD_CHOICES, default=METHOD_APP)
    sent = models.BooleanField(default=False)

    @property
    def remind_at(self):
        return self.event.start - timedelta(minutes=self.minutes_before)


class AudioUpload(TimestampedModel):
    """A recorded client conversation, uploaded via presigned URL and then
    transcribed (multilingual) to feed legal research."""

    STATUS_PENDING = 'pending'
    STATUS_UPLOADED = 'uploaded'
    STATUS_TRANSCRIBING = 'transcribing'
    STATUS_TRANSCRIBED = 'transcribed'
    STATUS_FAILED = 'failed'

    firm = models.ForeignKey(LawFirm, on_delete=models.CASCADE, related_name='audio_uploads')
    case = models.ForeignKey(
        Case, on_delete=models.SET_NULL, null=True, blank=True, related_name='audio_uploads'
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+'
    )
    filename = models.CharField(max_length=512)
    content_type = models.CharField(max_length=120, blank=True, default='')
    storage_key = models.CharField(max_length=1024)
    size = models.BigIntegerField(null=True, blank=True)
    language = models.CharField(
        max_length=16, blank=True, default='',
        help_text='ISO code, or blank for auto-detect (multilingual).',
    )
    status = models.CharField(max_length=16, default=STATUS_PENDING)
    error = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['-created_at']


class Transcript(TimestampedModel):
    upload = models.OneToOneField(
        AudioUpload, on_delete=models.CASCADE, related_name='transcript'
    )
    text = models.TextField(blank=True, default='')
    detected_language = models.CharField(max_length=16, blank=True, default='')
    segments = models.JSONField(default=list, blank=True)
    provider = models.CharField(max_length=64, blank=True, default='')
