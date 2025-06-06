import asyncio
import logging
import os
from pathlib import Path

from django.conf import settings
from django.http import FileResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response

from .serializers import (
    ChatRequestSerializer, 
    ChatResponseSerializer,
    CrawlRequestSerializer,
    StatusResponseSerializer,
    SampleQuestionsSerializer
)

from .signals import rag

# Configure logging
logger = logging.getLogger(__name__)

# Global crawl task
crawl_task = None

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
        response = await rag.get_response_with_context(
            query=query,
            site_filter=site_filter,
            model_name=model_name
        )
        return response
    
    def post(self, request):
        serializer = ChatRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        # Check if SimGrag is initialized
        if not rag:
            return Response(
                {"error": "Service not yet initialized"}, 
                status=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        
        try:
            # Process the query
            query = serializer.validated_data['query']
            site_filter = serializer.validated_data.get('site_filter')
            model_name = serializer.validated_data.get('model_name', 'llama3')
            
            logger.info(f"Processing query: {query}")
            
            # First get relevant context chunks
            context_results = rag.query(
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
            
            # Get response from SimGrag (use asyncio to run the async function)
            response = asyncio.run(self._get_response(
                query=query,
                site_filter=site_filter,
                model_name=model_name
            ))
            
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
                {"error": f"Error processing query: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class StatusView(APIView):
    """Get the current status of the API"""
    serializer_class = StatusResponseSerializer
    
    def get(self, request):
        if not rag:
            return Response({
                "status": "initializing",
                "message": "SimGrag is still initializing"
            })
        
        if crawl_task and not crawl_task.done():
            return Response({
                "status": "crawling",
                "message": "Website crawling is in progress"
            })
        
        return Response({
            "status": "ready",
            "message": "Kenya Law Assistant is ready for queries"
        })

@method_decorator(csrf_exempt, name='dispatch')
class CrawlView(APIView):
    """Start a crawl of the Kenya Law websites"""
    serializer_class = CrawlRequestSerializer
    
    async def _do_crawl(self, max_pages, max_depth, resume):
        try:
            logger.info(f"Starting crawl with max_pages={max_pages}, max_depth={max_depth}")
            await rag.crawl_sites(
                max_pages=max_pages,
                max_depth=max_depth,
                resume=resume
            )
            logger.info("Crawl completed successfully")
        except Exception as e:
            logger.error(f"Crawl failed: {str(e)}")
    
    def post(self, request):
        global rag, crawl_task
        
        serializer = CrawlRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        # Check if SimGrag is initialized
        if not rag:
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
