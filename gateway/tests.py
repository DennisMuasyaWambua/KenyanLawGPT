"""Gateway handler tests covering the Google, invite and calendar flows
(plus the presigned audio-upload + transcription path).

External seams are patched so the suite is hermetic: Google verification, the
IE transcription call and document ingestion never touch the network.
"""
from unittest import mock

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APIClient, APITestCase

from .models import AudioUpload, CalendarEvent, Case, Invite, LawFirm, Membership

User = get_user_model()


def auth(client, token, firm_id=None):
    client.credentials(HTTP_AUTHORIZATION=f'Token {token}')
    if firm_id:
        client.credentials(HTTP_AUTHORIZATION=f'Token {token}', HTTP_X_FIRM_ID=str(firm_id))
    return client


class SignUpAndLoginTests(APITestCase):
    def test_signup_creates_firm_owner_and_token(self):
        resp = self.client.post(reverse('gw-signup'), {
            'firm_name': 'Wanjiku & Co Advocates',
            'email': 'Owner@example.com',
            'password': 'supersecret1',
            'first_name': 'Owner',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertIn('token', resp.data)
        self.assertEqual(len(resp.data['memberships']), 1)
        self.assertEqual(resp.data['memberships'][0]['role'], Membership.ROLE_OWNER)
        # Email is normalised to lowercase and used as the username.
        self.assertTrue(User.objects.filter(username='owner@example.com').exists())
        self.assertEqual(LawFirm.objects.count(), 1)

    def test_signup_rejects_duplicate_email(self):
        payload = {'firm_name': 'A', 'email': 'dup@example.com', 'password': 'password12'}
        self.client.post(reverse('gw-signup'), payload, format='json')
        resp = self.client.post(reverse('gw-signup'), payload, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_login_returns_token(self):
        self.client.post(reverse('gw-signup'), {
            'firm_name': 'A', 'email': 'log@example.com', 'password': 'password12',
        }, format='json')
        resp = self.client.post(reverse('gw-login'), {
            'email': 'log@example.com', 'password': 'password12',
        }, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('token', resp.data)

    def test_login_bad_password(self):
        self.client.post(reverse('gw-signup'), {
            'firm_name': 'A', 'email': 'log2@example.com', 'password': 'password12',
        }, format='json')
        resp = self.client.post(reverse('gw-login'), {
            'email': 'log2@example.com', 'password': 'wrong',
        }, format='json')
        self.assertEqual(resp.status_code, 401)


class GoogleAuthTests(APITestCase):
    CLAIMS = {
        'email': 'grace@example.com',
        'email_verified': True,
        'sub': '12345',
        'given_name': 'Grace',
        'family_name': 'Mumbi',
    }

    @mock.patch('gateway.views.verify_google_id_token')
    def test_google_signup_creates_firm(self, verify):
        verify.return_value = dict(self.CLAIMS)
        resp = self.client.post(reverse('gw-google'), {
            'credential': 'fake-google-jwt',
            'firm_name': 'Mumbi Legal',
        }, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertTrue(resp.data['created'])
        self.assertEqual(len(resp.data['memberships']), 1)
        user = User.objects.get(username='grace@example.com')
        self.assertFalse(user.has_usable_password())

    @mock.patch('gateway.views.verify_google_id_token')
    def test_google_signin_existing_user_no_duplicate_firm(self, verify):
        verify.return_value = dict(self.CLAIMS)
        # First call signs up with a firm.
        self.client.post(reverse('gw-google'),
                         {'credential': 'x', 'firm_name': 'Mumbi Legal'}, format='json')
        # Second call (no firm_name) should just sign in — no new firm.
        resp = self.client.post(reverse('gw-google'), {'credential': 'x'}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.data['created'])
        self.assertEqual(LawFirm.objects.count(), 1)

    @mock.patch('gateway.views.verify_google_id_token')
    def test_google_rejected_credential(self, verify):
        from .auth import GoogleAuthError

        verify.side_effect = GoogleAuthError('Google rejected the credential.')
        resp = self.client.post(reverse('gw-google'), {'credential': 'bad'}, format='json')
        self.assertEqual(resp.status_code, 401)


class InviteFlowTests(APITestCase):
    def setUp(self):
        resp = self.client.post(reverse('gw-signup'), {
            'firm_name': 'Otieno Advocates',
            'email': 'boss@example.com',
            'password': 'password12',
        }, format='json')
        self.owner_token = resp.data['token']
        self.firm_id = resp.data['memberships'][0]['firm']['id']

    def _owner(self):
        return auth(APIClient(), self.owner_token, self.firm_id)

    def test_owner_can_invite_and_staff_can_accept(self):
        resp = self._owner().post(reverse('gw-invites'), {
            'email': 'newstaff@example.com', 'role': 'staff', 'title': 'Associate',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        token = resp.data['accept_token']

        # Public preview works before acceptance.
        preview = self.client.get(reverse('gw-invite-preview', args=[token]))
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.data['firm_name'], 'Otieno Advocates')

        # Accept: creates the user, membership and a login token.
        accept = self.client.post(reverse('gw-invite-accept'), {
            'token': token, 'password': 'staffpass123', 'first_name': 'New',
        }, format='json')
        self.assertEqual(accept.status_code, 200, accept.data)
        self.assertIn('token', accept.data)
        self.assertEqual(len(accept.data['memberships']), 1)
        self.assertEqual(Membership.objects.filter(firm_id=self.firm_id).count(), 2)

        invite = Invite.objects.get(token=token)
        self.assertEqual(invite.status, Invite.STATUS_ACCEPTED)

    def test_staff_cannot_invite(self):
        # Onboard a staff member first.
        inv = self._owner().post(reverse('gw-invites'),
                                 {'email': 's@example.com'}, format='json')
        self.client.post(reverse('gw-invite-accept'), {
            'token': inv.data['accept_token'], 'password': 'staffpass123',
        }, format='json')
        staff_login = self.client.post(reverse('gw-login'), {
            'email': 's@example.com', 'password': 'staffpass123',
        }, format='json')
        staff = auth(APIClient(), staff_login.data['token'], self.firm_id)

        resp = staff.post(reverse('gw-invites'),
                          {'email': 'another@example.com'}, format='json')
        self.assertEqual(resp.status_code, 403)

    def test_revoked_invite_cannot_be_accepted(self):
        inv = self._owner().post(reverse('gw-invites'),
                                 {'email': 'rev@example.com'}, format='json')
        invite = Invite.objects.get(token=inv.data['accept_token'])
        self._owner().post(reverse('gw-invite-revoke', args=[invite.id]))
        resp = self.client.post(reverse('gw-invite-accept'), {
            'token': invite.token, 'password': 'password12',
        }, format='json')
        self.assertEqual(resp.status_code, 404)


class CalendarFlowTests(APITestCase):
    def setUp(self):
        resp = self.client.post(reverse('gw-signup'), {
            'firm_name': 'Kamau LLP', 'email': 'a@example.com', 'password': 'password12',
        }, format='json')
        self.token = resp.data['token']
        self.firm_id = resp.data['memberships'][0]['firm']['id']
        self.client_a = auth(APIClient(), self.token, self.firm_id)

    def _event(self, **over):
        payload = {
            'title': 'Client meeting',
            'start': '2026-09-01T09:00:00Z',
            'end': '2026-09-01T10:00:00Z',
            'is_shared': False,
            'reminders': [{'minutes_before': 30, 'method': 'app'}],
        }
        payload.update(over)
        return payload

    def test_create_personal_event_with_reminder(self):
        resp = self.client_a.post(reverse('gw-events'), self._event(), format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(len(resp.data['reminders']), 1)
        self.assertEqual(CalendarEvent.objects.count(), 1)

    def test_end_before_start_is_rejected(self):
        resp = self.client_a.post(
            reverse('gw-events'),
            self._event(start='2026-09-01T10:00:00Z', end='2026-09-01T09:00:00Z'),
            format='json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_scope_filters_personal_vs_shared(self):
        self.client_a.post(reverse('gw-events'),
                           self._event(title='Mine', is_shared=False), format='json')
        self.client_a.post(reverse('gw-events'),
                           self._event(title='Firmwide', is_shared=True), format='json')

        shared = self.client_a.get(reverse('gw-events'), {'scope': 'shared'})
        self.assertEqual([e['title'] for e in shared.data], ['Firmwide'])
        personal = self.client_a.get(reverse('gw-events'), {'scope': 'personal'})
        self.assertEqual([e['title'] for e in personal.data], ['Mine'])

    def test_personal_event_hidden_from_other_member(self):
        self.client_a.post(reverse('gw-events'),
                           self._event(title='Private', is_shared=False), format='json')
        self.client_a.post(reverse('gw-events'),
                           self._event(title='Shared', is_shared=True), format='json')

        # Second member of the same firm.
        inv = self.client_a.post(reverse('gw-invites'),
                                 {'email': 'b@example.com'}, format='json')
        self.client.post(reverse('gw-invite-accept'),
                         {'token': inv.data['accept_token'], 'password': 'password12'},
                         format='json')
        login_b = self.client.post(reverse('gw-login'),
                                   {'email': 'b@example.com', 'password': 'password12'},
                                   format='json')
        client_b = auth(APIClient(), login_b.data['token'], self.firm_id)

        visible = client_b.get(reverse('gw-events'), {'scope': 'all'})
        titles = {e['title'] for e in visible.data}
        self.assertIn('Shared', titles)
        self.assertNotIn('Private', titles)

    def test_update_and_delete_event(self):
        created = self.client_a.post(reverse('gw-events'), self._event(), format='json')
        event_id = created.data['id']
        patched = self.client_a.patch(
            reverse('gw-event-detail', args=[event_id]),
            {'title': 'Updated'}, format='json',
        )
        self.assertEqual(patched.status_code, 200)
        self.assertEqual(patched.data['title'], 'Updated')
        deleted = self.client_a.delete(reverse('gw-event-detail', args=[event_id]))
        self.assertEqual(deleted.status_code, 204)
        self.assertEqual(CalendarEvent.objects.count(), 0)

    def test_requires_authentication(self):
        resp = APIClient().get(reverse('gw-events'))
        self.assertEqual(resp.status_code, 401)


class AudioTranscriptionTests(APITestCase):
    def setUp(self):
        resp = self.client.post(reverse('gw-signup'), {
            'firm_name': 'Mwangi & Partners', 'email': 'c@example.com',
            'password': 'password12',
        }, format='json')
        self.token = resp.data['token']
        self.firm_id = resp.data['memberships'][0]['firm']['id']
        self.api = auth(APIClient(), self.token, self.firm_id)

    def test_presign_upload_and_transcribe(self):
        # 1. Presign.
        presign = self.api.post(reverse('gw-audio-presign'), {
            'filename': 'client.webm', 'content_type': 'audio/webm', 'language': '',
        }, format='json')
        self.assertEqual(presign.status_code, 201, presign.data)
        audio_id = presign.data['audio']['id']
        upload_url = presign.data['upload']['upload_url']
        self.assertEqual(presign.data['upload']['storage'], 'local')

        # 2. PUT the bytes to the signed local upload sink.
        put = self.client.put(upload_url, b'RIFFfakeaudio',
                              content_type='audio/webm')
        self.assertEqual(put.status_code, 200, getattr(put, 'data', put))

        # 3. Mark uploaded.
        done = self.api.post(reverse('gw-audio-complete', args=[audio_id]))
        self.assertEqual(done.data['status'], AudioUpload.STATUS_UPLOADED)

        # 4. Transcribe (IE call patched).
        fake = {
            'text': 'Habari, ninahitaji ushauri wa kisheria.',
            'language': 'sw',
            'segments': [{'start': 0, 'end': 3, 'text': 'Habari'}],
            'provider': 'ie',
        }
        with mock.patch('gateway.transcription.transcribe_audio', return_value=fake):
            tr = self.api.post(reverse('gw-audio-transcribe', args=[audio_id]))
        self.assertEqual(tr.status_code, 200, tr.data)
        self.assertEqual(tr.data['status'], AudioUpload.STATUS_TRANSCRIBED)
        self.assertEqual(tr.data['transcript']['detected_language'], 'sw')
        self.assertIn('ushauri', tr.data['transcript']['text'])

    def test_transcribe_failure_marks_failed(self):
        presign = self.api.post(reverse('gw-audio-presign'),
                                {'filename': 'x.webm'}, format='json')
        audio_id = presign.data['audio']['id']
        self.client.put(presign.data['upload']['upload_url'], b'data',
                        content_type='audio/webm')
        from .transcription import TranscriptionError

        with mock.patch('gateway.transcription.transcribe_audio',
                        side_effect=TranscriptionError('boom')):
            tr = self.api.post(reverse('gw-audio-transcribe', args=[audio_id]))
        self.assertEqual(tr.status_code, 502)
        self.assertEqual(AudioUpload.objects.get(id=audio_id).status,
                         AudioUpload.STATUS_FAILED)


class CaseDocumentTests(APITestCase):
    def setUp(self):
        resp = self.client.post(reverse('gw-signup'), {
            'firm_name': 'Njoroge Advocates', 'email': 'd@example.com',
            'password': 'password12',
        }, format='json')
        self.token = resp.data['token']
        self.firm_id = resp.data['memberships'][0]['firm']['id']
        self.api = auth(APIClient(), self.token, self.firm_id)

    def test_case_document_presign_and_complete_triggers_ingestion(self):
        case = self.api.post(reverse('gw-cases'),
                             {'title': 'Estate of X'}, format='json')
        case_id = case.data['id']

        presign = self.api.post(
            reverse('gw-case-doc-presign', args=[case_id]),
            {'filename': 'affidavit.pdf', 'content_type': 'application/pdf'},
            format='json',
        )
        self.assertEqual(presign.status_code, 201, presign.data)
        doc_id = presign.data['document']['id']
        self.client.put(presign.data['upload']['upload_url'], b'%PDF-1.4 fake',
                        content_type='application/pdf')

        def fake_ingest(doc):
            doc.status = doc.STATUS_INGESTED
            doc.chunk_count = 3
            doc.save()
            return 3

        with mock.patch('gateway.ingestion.ingest_document', side_effect=fake_ingest):
            done = self.api.post(reverse('gw-doc-complete', args=[doc_id]))
        self.assertEqual(done.status_code, 200, done.data)
        self.assertEqual(done.data['status'], 'ingested')
        self.assertEqual(done.data['chunk_count'], 3)

    def test_cases_are_scoped_to_firm(self):
        # Another firm's case is invisible.
        other = self.client.post(reverse('gw-signup'), {
            'firm_name': 'Other LLP', 'email': 'e@example.com', 'password': 'password12',
        }, format='json')
        other_api = auth(APIClient(), other.data['token'],
                         other.data['memberships'][0]['firm']['id'])
        other_api.post(reverse('gw-cases'), {'title': 'Secret'}, format='json')

        mine = self.api.get(reverse('gw-cases'))
        self.assertEqual(mine.data, [])
