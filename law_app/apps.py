from django.apps import AppConfig


class LawAppConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'law_app'
    
    def ready(self):
        import sys
        from . import signals

        # Initialize SimGrag when the server starts. Skip for management
        # commands like migrate/makemigrations (the post_migrate signal
        # covers migrate), so they don't pay the model-loading cost twice.
        if any(cmd in sys.argv for cmd in ('runserver', 'gunicorn')) or 'manage.py' not in sys.argv[0]:
            signals.init_rag()
