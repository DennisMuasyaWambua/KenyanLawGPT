from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic.base import RedirectView

urlpatterns = [
    path('admin/', admin.site.urls),
    # Add redirects for common endpoints that might be accessed directly
    path('status/', RedirectView.as_view(url='/api/status/', permanent=False)),
    path('api/status', RedirectView.as_view(url='/api/status/', permanent=False)),
    path('sample-questions/', RedirectView.as_view(url='/api/sample-questions/', permanent=False)),
    path('chat/', RedirectView.as_view(url='/api/chat/', permanent=False)),
    path('crawl/', RedirectView.as_view(url='/api/crawl/', permanent=False)),
    # Multi-tenant SaaS gateway (auth, firms, calendars, cases, transcription)
    path('', include('gateway.urls')),
    # Include the app URLs
    path('', include('law_app.urls')),
]

# Serve static files during development
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
