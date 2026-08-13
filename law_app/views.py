import asyncio
import json
import logging
import os
from pathlib import Path

from django.conf import settings
from django.http import FileResponse, HttpResponse, StreamingHttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response

from .serializers import (
    ChatRequestSerializer,
    ChatResponseSerializer,
    CrawlRequestSerializer,
    DraftRequestSerializer,
    StatusResponseSerializer,
    SampleQuestionsSerializer
)

from . import signals

# Configure logging
logger = logging.getLogger(__name__)

# Global crawl task
crawl_task = None


def _sse_response(meta, chunks):
    """Wrap a ``StreamChunk`` iterator in a Server-Sent Events response.

    Emits one ``meta`` event first (backend + any sources), then per chunk a
    ``reasoning`` event (the model's "thinking…", for reasoning models) or a
    ``delta`` event (answer text), and finally a ``done`` event. A failure
    mid-stream is surfaced as an ``error`` event rather than a broken connection.
    """
    def _events():
        yield f"data: {json.dumps({'type': 'meta', **meta})}\n\n"
        try:
            for chunk in chunks:
                event = 'reasoning' if chunk.kind == 'reasoning' else 'delta'
                yield f"data: {json.dumps({'type': event, 'delta': chunk.text})}\n\n"
        except Exception as exc:  # mid-stream backend failure (cannot fall back now)
            logger.error(f"Stream failed after start: {exc}")
            yield f"data: {json.dumps({'type': 'error', 'error': str(exc)})}\n\n"
            return
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    resp = StreamingHttpResponse(_events(), content_type="text/event-stream")
    resp["Cache-Control"] = "no-cache"
    resp["X-Accel-Buffering"] = "no"  # disable proxy buffering (nginx) so tokens flush
    return resp

class IndexView(APIView):
    """Serve the index.html file"""
    
    def get(self, request):
        index_path = Path(settings.BASE_DIR) / "static" / "index.html"
        if index_path.exists():
            return FileResponse(open(index_path, 'rb'))
        else:
            return Response({"status": "ok", "message": "Kenya Law Assistant API is running"})

class APIRootView(APIView):
    """API root endpoint to check if API is running"""
    serializer_class = StatusResponseSerializer
    
    def get(self, request):
        return Response({
            "status": "ok",
            "message": "Kenya Law Assistant API is running"
        })

class SampleQuestionsView(APIView):
    """Get a list of sample questions to try"""
    serializer_class = SampleQuestionsSerializer
    
    def get(self, request):
        return Response({
            "questions": [
                "What are the key provisions of the Kenyan Constitution?",
                "What is the process for filing a case in the Kenyan High Court?",
                "Can you explain the Land Registration Act in Kenya?",
                "What are the different types of courts in Kenya?",
                "What rights are protected under the Bill of Rights in Kenya?",
                "How does Kenya's legal system handle intellectual property?",
                "What are the requirements for starting a business in Kenya?",
                "Can you explain how divorce proceedings work in Kenya?",
                "What laws govern environmental protection in Kenya?",
                "How is the judiciary structured in Kenya?"
            ]
        })

@method_decorator(csrf_exempt, name='dispatch')
class ChatView(APIView):
    """Process a chat request using the Kenya Law Assistant"""
    serializer_class = ChatRequestSerializer
    
    async def _get_response(self, query, site_filter, model_name):
        # Get response from SimGrag
        try:
            response = await signals.rag.get_response_with_context(
                query=query,
                site_filter=site_filter,
                model_name=model_name
            )
            return response
        except Exception as e:
            logger.error(f"Error getting response with context: {str(e)}")
            return f"Error: {str(e)}\n\nPlease make sure Ollama is running with the '{model_name}' model."
    
    def post(self, request):
        serializer = ChatRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        # Check if SimGrag is initialized
        if not signals.rag:
            return Response(
                {"error": "Service not yet initialized. Please try again later."}, 
                status=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        
        try:
            # Process the query
            query = serializer.validated_data['query']
            site_filter = serializer.validated_data.get('site_filter')
            model_name = serializer.validated_data.get('model_name', 'llama3')
            want_stream = serializer.validated_data.get('stream', False)

            logger.info(f"Processing query: {query} (stream={want_stream})")

            # Streaming path: GMI (primary) -> Ollama, surfaced token-by-token
            # over SSE. Retrieval + backend selection happen up front, so the
            # meta event already carries sources and the resolved backend.
            if want_stream:
                try:
                    stream_result, sources = signals.rag.stream_response_with_context(
                        query=query, site_filter=site_filter, model_name=model_name,
                    )
                except Exception as exc:
                    logger.error(f"Error starting stream: {exc}")
                    return Response(
                        {"error": f"Error processing query: {exc}", "query": query},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    )
                if not stream_result.served_by.startswith("gmi:"):
                    logger.warning(
                        "Chat stream NOT served by GMI (%s). Reason: %s",
                        stream_result.served_by, stream_result.fallback_reason or "unknown",
                    )
                return _sse_response(
                    {"served_by": stream_result.served_by, "sources": sources, "query": query},
                    stream_result.chunks,
                )

            try:
                # First get relevant context chunks
                context_results = signals.rag.query(
                    query_text=query,
                    top_k=5,
                    site_filter=site_filter
                )
                
                # Extract sources from context results
                sources = []
                for result in context_results:
                    metadata = result["metadata"]
                    url = metadata.get("url", "Unknown")
                    title = metadata.get("title", "Untitled")
                    
                    # Avoid duplicate sources
                    source_info = {"url": url, "title": title}
                    if source_info not in sources:
                        sources.append(source_info)
            except Exception as e:
                logger.error(f"Error querying context: {str(e)}")
                sources = []
                context_results = []
            
            # Create a new event loop for the async function instead of using asyncio.run()
            # which creates a new loop and closes it (problematic in Django's synchronous view)
            loop = asyncio.new_event_loop()
            try:
                response = loop.run_until_complete(self._get_response(
                    query=query,
                    site_filter=site_filter,
                    model_name=model_name
                ))
            finally:
                loop.close()
            
            # Log and return the response
            logger.info(f"Generated response for query: {query[:50]}...")
            
            return Response({
                "response": response,
                "sources": sources,
                "query": query
            })
            
        except Exception as e:
            logger.error(f"Error processing query: {str(e)}")
            return Response(
                {"error": f"Error processing query: {str(e)}",
                 "query": serializer.validated_data.get('query', '')},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

@method_decorator(csrf_exempt, name='dispatch')
class DraftView(APIView):
    """Draft a legal document with the fast GMI drafting model (Ollama fallback).

    POST an ``instruction`` (and optional ``context``). Streams the draft over
    SSE by default (``stream=true``); set ``stream=false`` for a single JSON
    response. ``contains_client_data`` gates GMI use for real client material.
    """
    serializer_class = DraftRequestSerializer

    def post(self, request):
        serializer = DraftRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        if not signals.rag:
            return Response(
                {"error": "Service not yet initialized. Please try again later."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        instruction = serializer.validated_data['instruction']
        context = serializer.validated_data.get('context') or None
        contains_client_data = serializer.validated_data.get('contains_client_data', False)
        want_stream = serializer.validated_data.get('stream', True)

        logger.info(f"Drafting request (stream={want_stream}, client_data={contains_client_data})")

        try:
            stream_result = signals.rag.stream_draft(
                instruction=instruction,
                context=context,
                contains_client_data=contains_client_data,
            )
        except Exception as exc:
            logger.error(f"Error starting draft: {exc}")
            return Response(
                {"error": f"Error drafting document: {exc}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        if not stream_result.served_by.startswith("gmi:"):
            logger.warning(
                "Draft NOT served by GMI (%s). Reason: %s",
                stream_result.served_by, stream_result.fallback_reason or "unknown",
            )

        if want_stream:
            return _sse_response({"served_by": stream_result.served_by}, stream_result.chunks)

        # Non-streaming: drain the iterator into one response body, keeping only
        # the answer (reasoning chunks are the model's scratchpad, not output).
        text = "".join(c.text for c in stream_result.chunks if c.kind == "content")
        return Response({"draft": text, "served_by": stream_result.served_by})


class StatusView(APIView):
    """Get the current status of the API"""
    serializer_class = StatusResponseSerializer
    
    def get(self, request):
        # Check if ollama is running
        try:
            import requests
            import os
            
            # Get Ollama host from environment variable or use default
            ollama_host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
            
            # Check if Ollama is running
            try:
                response = requests.get(f"{ollama_host}/api/tags", timeout=2)
                ollama_status = "running" if response.status_code == 200 else "error"
                models = [model.get("name") for model in response.json().get("models", [])]
                ollama_models = ", ".join(models) if models else "no models found"
            except Exception:
                ollama_status = "not running"
                ollama_models = "N/A"
        except Exception as e:
            ollama_status = f"error checking: {str(e)}"
            ollama_models = "N/A"
        
        if not signals.rag:
            return Response({
                "status": "initializing",
                "message": f"SimGrag is still initializing. Ollama status: {ollama_status}, available models: {ollama_models}"
            })
        
        if crawl_task and not crawl_task.done():
            return Response({
                "status": "crawling",
                "message": f"Website crawling is in progress. Ollama status: {ollama_status}, available models: {ollama_models}"
            })
        
        return Response({
            "status": "ready",
            "message": f"Kenya Law Assistant is ready for queries. Ollama status: {ollama_status}, available models: {ollama_models}"
        })

@method_decorator(csrf_exempt, name='dispatch')
class CrawlView(APIView):
    """Start a crawl of the Kenya Law websites"""
    serializer_class = CrawlRequestSerializer
    
    async def _do_crawl(self, max_pages, max_depth, resume):
        try:
            logger.info(f"Starting crawl with max_pages={max_pages}, max_depth={max_depth}")
            await signals.rag.crawl_sites(
                max_pages=max_pages,
                max_depth=max_depth,
                resume=resume
            )
            logger.info("Crawl completed successfully")
        except Exception as e:
            logger.error(f"Crawl failed: {str(e)}")
    
    def post(self, request):
        global crawl_task
        
        serializer = CrawlRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        # Check if SimGrag is initialized
        if not signals.rag:
            return Response(
                {"error": "Service not yet initialized"}, 
                status=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        
        # Check if a crawl is already in progress
        if crawl_task and not crawl_task.done():
            return Response({
                "status": "in_progress",
                "message": "A crawl is already in progress"
            })
        
        # Start the crawl in the background using asyncio
        max_pages = serializer.validated_data.get('max_pages', 100)
        max_depth = serializer.validated_data.get('max_depth', 3)
        resume = serializer.validated_data.get('resume', True)
        
        crawl_task = asyncio.ensure_future(self._do_crawl(
            max_pages=max_pages,
            max_depth=max_depth,
            resume=resume
        ))
        
        return Response({
            "status": "started",
            "message": f"Started crawling with max_pages={max_pages}, max_depth={max_depth}"
        })
