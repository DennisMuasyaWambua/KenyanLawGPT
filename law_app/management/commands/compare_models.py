"""A/B compare two GMI-hosted models on the same retrieval + prompt.

Runs the identical Kenya-law retrieval and prompt through the DeepSeek-R1 distill
and Qwen3-235B via GMI Cloud, printing latency, token usage and cost plus both
outputs side by side against the same citations — so you can eyeball quality and
cost before choosing a production primary. If a model is down it falls back to
Ollama for that row (served_by shows which provider answered).

    python manage.py compare_models "What are the grounds for divorce in Kenya?"
    python manage.py compare_models "..." --top-k 8 --site kenyalaw.org
"""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from law_app import signals
from law_app.providers.generation import generate_answer


class Command(BaseCommand):
    help = "A/B compare DeepSeek vs Qwen3 (via GMI Cloud) on one query."

    def add_arguments(self, parser):
        parser.add_argument("query", help="The legal question to run through both models.")
        parser.add_argument("--top-k", type=int, default=None, dest="top_k",
                            help="Number of context passages to retrieve.")
        parser.add_argument("--site", default=None, dest="site",
                            help="Optional site filter (kenyalaw.org / new.kenyalaw.org).")

    def handle(self, *args, **opts):
        if signals.rag is None:
            signals.init_rag()
        if signals.rag is None:
            raise CommandError("RAG engine is not initialised; cannot retrieve context.")

        query = opts["query"]
        # Retrieve + build the prompt ONCE so both models see identical input.
        prompt, context_text, sources = signals.rag.build_context_prompt(
            query, top_k=opts["top_k"], site_filter=opts["site"],
        )

        self.stdout.write(self.style.NOTICE(f"\nQuery: {query}"))
        self.stdout.write(f"Shared retrieval — {len(sources)} source(s):")
        for url, title in sources:
            self.stdout.write(f"  - {title or '(untitled)'}  {url}")

        contenders = [
            ("DeepSeek-R1-Distill", settings.GMI_CLOUD_DEEPSEEK_MODEL),
            ("Qwen3-235B", settings.GMI_CLOUD_QWEN_MODEL),
        ]
        for label, model in contenders:
            self.stdout.write(self.style.HTTP_INFO(f"\n===== {label} =====\n{model}"))
            if not model:
                self.stdout.write(self.style.WARNING("  (model env var not set — skipping)"))
                continue
            result = generate_answer(
                prompt, model=model, contains_client_data=False,
                ollama_fallback=lambda: signals.rag._ollama_generate(
                    prompt, "llama3", context_text),
            )
            self.stdout.write(
                f"served_by={result.served_by}  latency={result.latency_ms}ms  "
                f"input_tokens={result.prompt_tokens}  output_tokens={result.completion_tokens}  "
                f"cost=${result.cost_usd:.5f}"
            )
            if result.fallback_reason:
                self.stdout.write(self.style.WARNING(f"  fallback: {result.fallback_reason}"))
            self.stdout.write("\n" + (result.text or "").strip() + "\n")
