from django.urls import path

from . import views

urlpatterns = [
    # Auth & Google sign-in
    path('api/auth/signup/', views.SignUpView.as_view(), name='gw-signup'),
    path('api/auth/login/', views.LoginView.as_view(), name='gw-login'),
    path('api/auth/google/', views.GoogleAuthView.as_view(), name='gw-google'),
    path('api/auth/me/', views.MeView.as_view(), name='gw-me'),

    # Staff onboarding via invites
    path('api/firm/members/', views.MembersView.as_view(), name='gw-members'),
    path('api/firm/invites/', views.InvitesView.as_view(), name='gw-invites'),
    path('api/firm/invites/<uuid:invite_id>/revoke/',
         views.InviteRevokeView.as_view(), name='gw-invite-revoke'),
    # accept/ must precede the <token> preview so it isn't captured as a token.
    path('api/invites/accept/', views.InviteAcceptView.as_view(), name='gw-invite-accept'),
    path('api/invites/<str:token>/', views.InvitePreviewView.as_view(),
         name='gw-invite-preview'),

    # Calendars
    path('api/calendar/events/', views.CalendarEventsView.as_view(), name='gw-events'),
    path('api/calendar/events/<uuid:event_id>/',
         views.CalendarEventDetailView.as_view(), name='gw-event-detail'),

    # Cases + document ingestion
    path('api/cases/', views.CasesView.as_view(), name='gw-cases'),
    path('api/cases/<uuid:case_id>/documents/',
         views.CaseDocumentsView.as_view(), name='gw-case-docs'),
    path('api/cases/<uuid:case_id>/documents/presign/',
         views.CaseDocumentPresignView.as_view(), name='gw-case-doc-presign'),
    path('api/cases/<uuid:case_id>/search/',
         views.CaseSearchView.as_view(), name='gw-case-search'),
    path('api/documents/<uuid:document_id>/complete/',
         views.CaseDocumentCompleteView.as_view(), name='gw-doc-complete'),

    # Audio upload + transcription
    path('api/audio/presign/', views.AudioPresignView.as_view(), name='gw-audio-presign'),
    path('api/audio/', views.AudioPresignView.as_view(), name='gw-audio-list'),
    path('api/audio/<uuid:audio_id>/complete/',
         views.AudioCompleteView.as_view(), name='gw-audio-complete'),
    path('api/audio/<uuid:audio_id>/transcribe/',
         views.AudioTranscribeView.as_view(), name='gw-audio-transcribe'),

    # Local dev upload sink for presigned PUTs. The signed token embeds the
    # storage key, which contains slashes, so it needs the <path> converter.
    path('api/uploads/local/<path:token>', views.LocalUploadView.as_view(),
         name='gw-local-upload'),
]
