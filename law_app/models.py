from decimal import Decimal

from django.db import models
from django.db.models import F
from django.utils import timezone


class GmiSpend(models.Model):
    """Per-UTC-day accumulator of GMI Cloud token spend.

    One row per day — a new day means a fresh row, so the daily cost ceiling
    resets automatically (a rolling per-day window). Increments are atomic via
    ``F()`` expressions, but the cap is a *soft* boundary: the
    check-then-call-then-record sequence can overshoot slightly under
    concurrency, hardening on the next call. That is an acceptable trade for a
    testing cost guard and avoids per-request row locking.
    """
    day = models.DateField(unique=True)
    input_tokens = models.BigIntegerField(default=0)
    output_tokens = models.BigIntegerField(default=0)
    usd_spent = models.DecimalField(max_digits=12, decimal_places=6, default=0)

    class Meta:
        ordering = ["-day"]

    def __str__(self):
        return f"{self.day}: ${self.usd_spent}"

    @classmethod
    def today_spend_usd(cls) -> float:
        row = (cls.objects.filter(day=timezone.now().date())
               .values_list("usd_spent", flat=True).first())
        return float(row or 0)

    @classmethod
    def record(cls, input_tokens, output_tokens, cost_usd):
        """Atomically add usage + cost to today's row (creating it if needed)."""
        today = timezone.now().date()
        cls.objects.get_or_create(day=today)
        cls.objects.filter(day=today).update(
            input_tokens=F("input_tokens") + int(input_tokens),
            output_tokens=F("output_tokens") + int(output_tokens),
            usd_spent=F("usd_spent") + Decimal(str(cost_usd)),
        )
