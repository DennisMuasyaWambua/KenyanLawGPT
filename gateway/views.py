"""Gateway request handlers for WakiliAI.

Grouped by concern: auth & Google sign-in, firm/staff onboarding via invites,
calendars (personal + shared), cases & per-case document ingestion, and audio
upload + multilingual transcription. Object uploads use presigned URLs
(``gateway.storage``); external services (Google, IE transcription) are reached
through single, patchable seams.
"""
import logging

from django.contrib.auth import authenticate, get_user_model
from django.db import IntegrityError, transaction
from django.utils.text import slugify
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from rest_framework import status
from rest_framework.authentication import SessionAuthentication, TokenAuthentication
from rest_framework.authtoken.models import Token
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import storage
from .auth import GoogleAuthError, verify_google_id_token
from .models import (
    AudioUpload,
    Case,
    CaseDocument,
    CalendarEvent,
    Invite,
    LawFirm,
    Membership,
    Transcript,
)
from .serializers import (
    AudioUploadSerializer,
    CaseDocumentSerializer,
    CaseSerializer,
    CalendarEventSerializer,
    InviteSerializer,
    MembershipSerializer,
)

logger = logging.getLogger(__name__)
User = get_user_model()


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #
def _unique_slug(name):
    base = slugify(name) or 'firm'
    slug, i = base, 1
    while LawFirm.objects.filter(slug=slug).exists():
        i += 1
        slug = f'{base}-{i}'
    return slug


def _serialize_user(user):
    return {
        'id': user.id,
        'email': user.email,
        'first_name': user.first_name,
        'last_name': user.last_name,
    }


def _auth_payload(user):
    """The standard bundle returned by sign-up / sign-in: token, user, firms."""
    token, _ = Token.objects.get_or_create(user=user)
    memberships = (
        Membership.objects.filter(user=user).select_related('firm')
    )
    return {
        'token': token.key,
        'user': _serialize_user(user),
        'memberships': [
            {
                'firm': {
                    'id': str(m.firm_id),
                    'name': m.firm.name,
                    'slug': m.firm.slug,
                },
                'role': m.role,
            }
            for m in memberships
        ],
    }


class FirmScopedView(APIView):
    """Authenticated view that resolves the caller's active firm membership.

    The active firm is picked from the ``X-Firm-Id`` header, falling back to the
    user's first membership. Handlers call :meth:`membership` (400 if none) and
    get a firm-scoped queryset for free.
    """

    authentication_classes = [TokenAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def membership(self, request):
        qs = Membership.objects.filter(user=request.user).select_related('firm')
        firm_id = request.headers.get('X-Firm-Id')
        if firm_id:
            m = qs.filter(firm_id=firm_id).first()
        else:
            m = qs.first()
        return m

    def require_membership(self, request):
        m = self.membership(request)
        if m is None:
            raise _ApiProblem('You do not belong to a firm yet.', status.HTTP_403_FORBIDDEN)
        return m


class _ApiProblem(Exception):
    def __init__(self, message, code=status.HTTP_400_BAD_REQUEST):
        super().__init__(message)
        self.message = message
        self.code = code


def _handle_problem(fn):
    """Wrap a handler so _ApiProblem becomes a clean JSON error response."""

    def wrapper(self, request, *args, **kwargs):
        try:
            return fn(self, request, *args, **kwargs)
        except _ApiProblem as exc:
            return Response({'error': exc.message}, status=exc.code)

    return wrapper


# --------------------------------------------------------------------------- #
# Auth & Google sign-in
# --------------------------------------------------------------------------- #
@method_decorator(csrf_exempt, name='dispatch')
class SignUpView(APIView):
    """Register a new law firm and its owner in one step."""

    permission_classes = [AllowAny]

    @_handle_problem
    def post(self, request):
        data = request.data
        firm_name = (data.get('firm_name') or '').strip()
        email = (data.get('email') or '').strip().lower()
        password = data.get('password') or ''
        if not firm_name or not email or not password:
            raise _ApiProblem('firm_name, email and password are required.')
        if len(password) < 8:
            raise _ApiProblem('Password must be at least 8 characters.')
        if User.objects.filter(username=email).exists():
            raise _ApiProblem('An account with that email already exists.')

        with transaction.atomic():
            user = User.objects.create_user(
                username=email,
                email=email,
                password=password,
                first_name=(data.get('first_name') or '').strip(),
                last_name=(data.get('last_name') or '').strip(),
            )
            firm = LawFirm.objects.create(
                name=firm_name, slug=_unique_slug(firm_name), owner=user
            )
            Membership.objects.create(firm=firm, user=user, role=Membership.ROLE_OWNER)

        return Response(_auth_payload(user), status=status.HTTP_201_CREATED)


@method_decorator(csrf_exempt, name='dispatch')
class LoginView(APIView):
    permission_classes = [AllowAny]

    @_handle_problem
    def post(self, request):
        email = (request.data.get('email') or '').strip().lower()
        password = request.data.get('password') or ''
        user = authenticate(username=email, password=password)
        if user is None:
            raise _ApiProblem('Invalid email or password.', status.HTTP_401_UNAUTHORIZED)
        return Response(_auth_payload(user))


@method_decorator(csrf_exempt, name='dispatch')
class GoogleAuthView(APIView):
    """Sign in *or* sign up with Google.

    Verifies the Google ID token, finds or creates the matching user, and — if a
    ``firm_name`` is supplied and the user has no firm yet — provisions a firm
    with them as owner. Returns the same bundle as email sign-in.
    """

    permission_classes = [AllowAny]

    @_handle_problem
    def post(self, request):
        credential = request.data.get('credential') or request.data.get('id_token')
        try:
            claims = verify_google_id_token(credential)
        except GoogleAuthError as exc:
            raise _ApiProblem(str(exc), status.HTTP_401_UNAUTHORIZED)

        email = claims['email'].lower()
        with transaction.atomic():
            user, created = User.objects.get_or_create(
                username=email,
                defaults={
                    'email': email,
                    'first_name': claims.get('given_name', ''),
                    'last_name': claims.get('family_name', ''),
                },
            )
            if created:
                user.set_unusable_password()
                user.save(update_fields=['password'])

            firm_name = (request.data.get('firm_name') or '').strip()
            if firm_name and not Membership.objects.filter(user=user).exists():
                firm = LawFirm.objects.create(
                    name=firm_name, slug=_unique_slug(firm_name), owner=user
                )
                Membership.objects.create(
                    firm=firm, user=user, role=Membership.ROLE_OWNER
                )

        payload = _auth_payload(user)
        payload['created'] = created
        return Response(payload)


class MeView(FirmScopedView):
    def get(self, request):
        return Response(_auth_payload(request.user))


# --------------------------------------------------------------------------- #
# Staff onboarding via invites
# --------------------------------------------------------------------------- #
@method_decorator(csrf_exempt, name='dispatch')
class MembersView(FirmScopedView):
    @_handle_problem
    def get(self, request):
        m = self.require_membership(request)
        members = Membership.objects.filter(firm=m.firm).select_related('user')
        return Response(MembershipSerializer(members, many=True).data)


@method_decorator(csrf_exempt, name='dispatch')
class InvitesView(FirmScopedView):
    @_handle_problem
    def get(self, request):
        m = self.require_membership(request)
        invites = Invite.objects.filter(firm=m.firm).order_by('-created_at')
        return Response(InviteSerializer(invites, many=True).data)

    @_handle_problem
    def post(self, request):
        m = self.require_membership(request)
        if not m.can_manage:
            raise _ApiProblem('Only owners and admins can invite staff.',
                              status.HTTP_403_FORBIDDEN)
        email = (request.data.get('email') or '').strip().lower()
        if not email:
            raise _ApiProblem('email is required.')
        role = request.data.get('role') or Membership.ROLE_STAFF
        if role not in dict(Membership.ROLE_CHOICES):
            raise _ApiProblem('Invalid role.')
        if Membership.objects.filter(firm=m.firm, user__username=email).exists():
            raise _ApiProblem('That person is already a member of the firm.')

        invite = Invite.objects.create(
            firm=m.firm,
            email=email,
            role=role,
            title=(request.data.get('title') or '').strip(),
            invited_by=request.user,
        )
        # In production an email with this link would be sent; we return it so
        # the owner can share it (and tests can assert on it).
        data = InviteSerializer(invite).data
        data['accept_token'] = invite.token
        return Response(data, status=status.HTTP_201_CREATED)


@method_decorator(csrf_exempt, name='dispatch')
class InviteRevokeView(FirmScopedView):
    @_handle_problem
    def post(self, request, invite_id):
        m = self.require_membership(request)
        if not m.can_manage:
            raise _ApiProblem('Only owners and admins can revoke invites.',
                              status.HTTP_403_FORBIDDEN)
        invite = Invite.objects.filter(id=invite_id, firm=m.firm).first()
        if not invite:
            raise _ApiProblem('Invite not found.', status.HTTP_404_NOT_FOUND)
        invite.status = Invite.STATUS_REVOKED
        invite.save(update_fields=['status', 'updated_at'])
        return Response(InviteSerializer(invite).data)


@method_decorator(csrf_exempt, name='dispatch')
class InvitePreviewView(APIView):
    """Public: look up an invite by token so the accept page can render it."""

    permission_classes = [AllowAny]

    def get(self, request, token):
        invite = Invite.objects.filter(token=token).select_related('firm').first()
        if not invite or not invite.is_open:
            return Response({'error': 'This invite is no longer valid.'},
                            status=status.HTTP_404_NOT_FOUND)
        return Response({
            'firm_name': invite.firm.name,
            'email': invite.email,
            'role': invite.role,
        })


@method_decorator(csrf_exempt, name='dispatch')
class InviteAcceptView(APIView):
    """Public: accept an invite, creating/linking a user and their membership."""

    permission_classes = [AllowAny]

    @_handle_problem
    def post(self, request):
        token = request.data.get('token') or ''
        invite = Invite.objects.filter(token=token).select_related('firm').first()
        if not invite or not invite.is_open:
            raise _ApiProblem('This invite is no longer valid.', status.HTTP_404_NOT_FOUND)

        with transaction.atomic():
            user = User.objects.filter(username=invite.email).first()
            if user is None:
                password = request.data.get('password') or ''
                if len(password) < 8:
                    raise _ApiProblem('Password must be at least 8 characters.')
                user = User.objects.create_user(
                    username=invite.email,
                    email=invite.email,
                    password=password,
                    first_name=(request.data.get('first_name') or '').strip(),
                    last_name=(request.data.get('last_name') or '').strip(),
                )
            Membership.objects.get_or_create(
                firm=invite.firm,
                user=user,
                defaults={'role': invite.role, 'title': invite.title},
            )
            invite.status = Invite.STATUS_ACCEPTED
            invite.save(update_fields=['status', 'updated_at'])

        return Response(_auth_payload(user))


# --------------------------------------------------------------------------- #
# Calendars: personal + shared
# --------------------------------------------------------------------------- #
@method_decorator(csrf_exempt, name='dispatch')
class CalendarEventsView(FirmScopedView):
    @_handle_problem
    def get(self, request):
        from django.db.models import Q

        m = self.require_membership(request)
        scope = request.query_params.get('scope', 'all')
        # Personal events of the caller + all shared events in the firm.
        events = CalendarEvent.objects.filter(firm=m.firm).prefetch_related('reminders')
        if scope == 'personal':
            events = events.filter(owner=request.user, is_shared=False)
        elif scope == 'shared':
            events = events.filter(is_shared=True)
        else:
            events = events.filter(Q(is_shared=True) | Q(owner=request.user))
        start = request.query_params.get('from')
        end = request.query_params.get('to')
        if start:
            events = events.filter(start__gte=start)
        if end:
            events = events.filter(start__lte=end)
        return Response(CalendarEventSerializer(events, many=True).data)

    @_handle_problem
    def post(self, request):
        m = self.require_membership(request)
        serializer = CalendarEventSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(firm=m.firm, owner=request.user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


@method_decorator(csrf_exempt, name='dispatch')
class CalendarEventDetailView(FirmScopedView):
    def _get(self, request, m, event_id):
        from django.db.models import Q

        event = (
            CalendarEvent.objects.filter(firm=m.firm)
            .filter(Q(is_shared=True) | Q(owner=request.user))
            .filter(id=event_id)
            .first()
        )
        if not event:
            raise _ApiProblem('Event not found.', status.HTTP_404_NOT_FOUND)
        return event

    @_handle_problem
    def get(self, request, event_id):
        m = self.require_membership(request)
        return Response(CalendarEventSerializer(self._get(request, m, event_id)).data)

    @_handle_problem
    def put(self, request, event_id):
        return self._update(request, event_id, partial=False)

    @_handle_problem
    def patch(self, request, event_id):
        return self._update(request, event_id, partial=True)

    def _update(self, request, event_id, partial):
        m = self.require_membership(request)
        event = self._get(request, m, event_id)
        if event.owner_id != request.user.id and not m.can_manage:
            raise _ApiProblem('You can only edit your own events.',
                              status.HTTP_403_FORBIDDEN)
        serializer = CalendarEventSerializer(event, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    @_handle_problem
    def delete(self, request, event_id):
        m = self.require_membership(request)
        event = self._get(request, m, event_id)
        if event.owner_id != request.user.id and not m.can_manage:
            raise _ApiProblem('You can only delete your own events.',
                              status.HTTP_403_FORBIDDEN)
        event.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------- #
# Cases + document ingestion
# --------------------------------------------------------------------------- #
@method_decorator(csrf_exempt, name='dispatch')
class CasesView(FirmScopedView):
    @_handle_problem
    def get(self, request):
        m = self.require_membership(request)
        cases = Case.objects.filter(firm=m.firm)
        return Response(CaseSerializer(cases, many=True).data)

    @_handle_problem
    def post(self, request):
        m = self.require_membership(request)
        serializer = CaseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(firm=m.firm, created_by=request.user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


def _get_case(request, m, case_id):
    case = Case.objects.filter(id=case_id, firm=m.firm).first()
    if not case:
        raise _ApiProblem('Case not found.', status.HTTP_404_NOT_FOUND)
    return case


@method_decorator(csrf_exempt, name='dispatch')
class CaseDocumentsView(FirmScopedView):
    @_handle_problem
    def get(self, request, case_id):
        m = self.require_membership(request)
        case = _get_case(request, m, case_id)
        docs = case.documents.all()
        return Response(CaseDocumentSerializer(docs, many=True).data)


@method_decorator(csrf_exempt, name='dispatch')
class CaseDocumentPresignView(FirmScopedView):
    """Issue a presigned upload URL for a new case document."""

    @_handle_problem
    def post(self, request, case_id):
        m = self.require_membership(request)
        case = _get_case(request, m, case_id)
        filename = (request.data.get('filename') or '').strip()
        if not filename:
            raise _ApiProblem('filename is required.')
        content_type = request.data.get('content_type') or ''
        key = storage.generate_storage_key('case-docs', m.firm_id, filename)
        doc = CaseDocument.objects.create(
            case=case,
            filename=filename,
            content_type=content_type,
            storage_key=key,
            size=request.data.get('size') or None,
            uploaded_by=request.user,
        )
        presign = storage.create_presigned_upload(key, content_type)
        return Response(
            {'document': CaseDocumentSerializer(doc).data, 'upload': presign},
            status=status.HTTP_201_CREATED,
        )


@method_decorator(csrf_exempt, name='dispatch')
class CaseDocumentCompleteView(FirmScopedView):
    """Mark a document uploaded and kick off ingestion into the vector store."""

    @_handle_problem
    def post(self, request, document_id):
        m = self.require_membership(request)
        doc = CaseDocument.objects.filter(
            id=document_id, case__firm=m.firm
        ).select_related('case').first()
        if not doc:
            raise _ApiProblem('Document not found.', status.HTTP_404_NOT_FOUND)
        doc.status = CaseDocument.STATUS_UPLOADED
        doc.save(update_fields=['status', 'updated_at'])

        from . import ingestion

        try:
            ingestion.ingest_document(doc)
        except Exception as exc:  # already recorded on the document
            logger.warning('Ingestion error for %s: %s', doc.id, exc)
        doc.refresh_from_db()
        return Response(CaseDocumentSerializer(doc).data)


@method_decorator(csrf_exempt, name='dispatch')
class CaseSearchView(FirmScopedView):
    """Retrieve the most relevant case-document chunks for a query — the read
    side of the ingestion pipeline that grounds the assistant's reasoning."""

    @_handle_problem
    def post(self, request, case_id):
        m = self.require_membership(request)
        case = _get_case(request, m, case_id)
        query = (request.data.get('query') or '').strip()
        if not query:
            raise _ApiProblem('query is required.')

        from law_app import signals
        from . import ingestion

        rag = signals.rag
        if rag is None or getattr(rag, 'embedding_model', None) is None:
            raise _ApiProblem('Search is not available yet — engine initialising.',
                              status.HTTP_503_SERVICE_UNAVAILABLE)
        collection = rag.chroma_client.get_or_create_collection(
            name=ingestion.collection_name_for_firm(m.firm_id)
        )
        embedding = rag.embedding_model.encode([query]).tolist()
        results = collection.query(
            query_embeddings=embedding,
            n_results=int(request.data.get('top_k') or 5),
            where={'case_id': str(case.id)},
        )
        docs = (results.get('documents') or [[]])[0]
        metas = (results.get('metadatas') or [[]])[0]
        chunks = [
            {'text': d, 'filename': (metas[i] or {}).get('filename', '')}
            for i, d in enumerate(docs)
        ]
        return Response({'query': query, 'chunks': chunks})


# --------------------------------------------------------------------------- #
# Audio upload + multilingual transcription
# --------------------------------------------------------------------------- #
@method_decorator(csrf_exempt, name='dispatch')
class AudioPresignView(FirmScopedView):
    @_handle_problem
    def get(self, request):
        m = self.require_membership(request)
        uploads = AudioUpload.objects.filter(firm=m.firm)
        return Response(AudioUploadSerializer(uploads, many=True).data)

    @_handle_problem
    def post(self, request):
        m = self.require_membership(request)
        filename = (request.data.get('filename') or '').strip()
        if not filename:
            raise _ApiProblem('filename is required.')
        content_type = request.data.get('content_type') or 'audio/webm'
        case = None
        if request.data.get('case'):
            case = _get_case(request, m, request.data['case'])
        key = storage.generate_storage_key('audio', m.firm_id, filename)
        upload = AudioUpload.objects.create(
            firm=m.firm,
            case=case,
            uploaded_by=request.user,
            filename=filename,
            content_type=content_type,
            storage_key=key,
            size=request.data.get('size') or None,
            language=(request.data.get('language') or '').strip(),
        )
        presign = storage.create_presigned_upload(key, content_type)
        return Response(
            {'audio': AudioUploadSerializer(upload).data, 'upload': presign},
            status=status.HTTP_201_CREATED,
        )


@method_decorator(csrf_exempt, name='dispatch')
class AudioCompleteView(FirmScopedView):
    @_handle_problem
    def post(self, request, audio_id):
        m = self.require_membership(request)
        upload = AudioUpload.objects.filter(id=audio_id, firm=m.firm).first()
        if not upload:
            raise _ApiProblem('Audio not found.', status.HTTP_404_NOT_FOUND)
        upload.status = AudioUpload.STATUS_UPLOADED
        upload.save(update_fields=['status', 'updated_at'])
        return Response(AudioUploadSerializer(upload).data)


@method_decorator(csrf_exempt, name='dispatch')
class AudioTranscribeView(FirmScopedView):
    @_handle_problem
    def post(self, request, audio_id):
        m = self.require_membership(request)
        upload = AudioUpload.objects.filter(id=audio_id, firm=m.firm).first()
        if not upload:
            raise _ApiProblem('Audio not found.', status.HTTP_404_NOT_FOUND)

        from .transcription import TranscriptionError, transcribe_audio

        upload.status = AudioUpload.STATUS_TRANSCRIBING
        upload.save(update_fields=['status', 'updated_at'])
        try:
            data = storage.read_object(upload.storage_key)
            result = transcribe_audio(
                data,
                filename=upload.filename,
                content_type=upload.content_type,
                language=upload.language,
            )
        except (TranscriptionError, FileNotFoundError, OSError) as exc:
            upload.status = AudioUpload.STATUS_FAILED
            upload.error = str(exc)[:1000]
            upload.save(update_fields=['status', 'error', 'updated_at'])
            raise _ApiProblem(str(exc), status.HTTP_502_BAD_GATEWAY)

        transcript, _ = Transcript.objects.update_or_create(
            upload=upload,
            defaults={
                'text': result['text'],
                'detected_language': result['language'],
                'segments': result['segments'],
                'provider': result['provider'],
            },
        )
        upload.status = AudioUpload.STATUS_TRANSCRIBED
        upload.error = ''
        upload.save(update_fields=['status', 'error', 'updated_at'])
        return Response(AudioUploadSerializer(upload).data)


# --------------------------------------------------------------------------- #
# Local (dev) upload sink for presigned PUTs
# --------------------------------------------------------------------------- #
@method_decorator(csrf_exempt, name='dispatch')
class LocalUploadView(APIView):
    """Receive the bytes for a signed local-upload token (dev backend only)."""

    permission_classes = [AllowAny]

    def put(self, request, token):
        try:
            key = storage.verify_local_token(token)
        except ValueError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        storage.save_local_object(key, request.body)
        return Response({'status': 'stored', 'key': key})
