from django.urls import path
from . import views

urlpatterns = [
    path('', views.IndexView.as_view(), name='index'),
    path('api/', views.APIRootView.as_view(), name='api-root'),
    path('api/sample-questions/', views.SampleQuestionsView.as_view(), name='sample-questions'),
    path('api/chat/', views.ChatView.as_view(), name='chat'),
    path('api/status/', views.StatusView.as_view(), name='status'),
    path('api/crawl/', views.CrawlView.as_view(), name='crawl'),
]
