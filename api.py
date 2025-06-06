"""
API for Kenya Law Assistant: Provides RESTful endpoints to interact with the SimGrag chatbot
"""
import asyncio
import uvicorn
from fastapi import FastAPI, HTTPException, Body, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
import logging
import os
from pathlib import Path

# Import the chatbot components
from law import SimGrag, LLMContextProvider, WebsiteVectorizer

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# File handler to save logs to disk
file_handler = logging.FileHandler("api.log")
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(file_handler)

# Initialize FastAPI app
app = FastAPI(
    title="Kenya Law Assistant API",
    description="API for querying Kenya Law content using RAG-powered chatbot",
    version="1.0.0"
)

# Mount static files directory
static_path = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(static_path)), name="static")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request models
class ChatRequest(BaseModel):
    query: str = Field(..., description="User query to the Kenya Law Assistant")
    site_filter: Optional[str] = Field(None, description="Optional site filter: 'kenyalaw.org' or 'new.kenyalaw.org'")
    model_name: str = Field("llama3", description="Model name to use with Ollama")

class CrawlRequest(BaseModel):
    max_pages: int = Field(100, description="Maximum number of pages to crawl")
    max_depth: int = Field(3, description="Maximum depth of links to follow")
    resume: bool = Field(True, description="Whether to resume from previous crawl")

# Response models
class ChatResponse(BaseModel):
    response: str = Field(..., description="The response from the Kenya Law Assistant")
    sources: List[Dict[str, str]] = Field([], description="Sources used to generate the response")
    query: str = Field(..., description="Original user query")

class StatusResponse(BaseModel):
    status: str = Field(..., description="Status of the operation")
    message: str = Field(..., description="Additional information")
    
class SampleQuestionsResponse(BaseModel):
    questions: List[str] = Field(..., description="List of sample questions")

# Global SimGrag instance
rag = None
crawl_task = None

@app.on_event("startup")
async def startup_event():
    """Initialize the SimGrag instance on startup"""
    global rag
    
    logger.info("Initializing SimGrag instance...")
    
    # Check for environment variables that might be set in Railway
    import os
    vector_db_path = os.environ.get("VECTOR_DB_PATH", "./vector_db")
    concurrent_requests = int(os.environ.get("CONCURRENT_REQUESTS", "4"))
    request_delay = float(os.environ.get("REQUEST_DELAY", "1.0"))
    
    # Create vector_db directory if it doesn't exist
    os.makedirs(vector_db_path, exist_ok=True)
    
    # Initialize SimGrag for both Kenya Law sites
    rag = SimGrag(
        vector_db_path=vector_db_path,
        chunk_size=1000,
        chunk_overlap=200,
        context_limit=4000,
        max_context_chunks=10
    )
    
    # Initialize vectorizers with conservative settings
    rag.initialize_vectorizers(
        concurrent_requests=concurrent_requests,  # Conservative to avoid overwhelming the server
        request_delay=request_delay               # Conservative delay
    )
    
    logger.info(f"SimGrag initialization complete. Using vector_db_path={vector_db_path}")

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    logger.info("API shutting down")
    
    # No explicit cleanup needed for SimGrag

@app.get("/", response_class=FileResponse)
async def root():
    """Serve the index.html file"""
    index_path = Path(__file__).parent / "static" / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    else:
        return {"status": "ok", "message": "Kenya Law Assistant API is running"}

@app.get("/api", response_model=StatusResponse)
async def api_root():
    """API root endpoint to check if API is running"""
    return {
        "status": "ok",
        "message": "Kenya Law Assistant API is running"
    }

@app.get("/sample-questions", response_model=SampleQuestionsResponse)
async def sample_questions():
    """Get a list of sample questions to try"""
    return {
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
    }

@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Process a chat request using the Kenya Law Assistant
    
    Args:
        request: Chat request containing the user query
        
    Returns:
        Chat response with the assistant's answer
    """
    global rag
    
    # Check if SimGrag is initialized
    if not rag:
        raise HTTPException(status_code=503, detail="Service not yet initialized")
    
    try:
        # Process the query
        logger.info(f"Processing query: {request.query}")
        
        # First get relevant context chunks
        context_results = rag.query(
            query_text=request.query,
            top_k=5,
            site_filter=request.site_filter
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
        
        # Get response from SimGrag
        response = await rag.get_response_with_context(
            query=request.query,
            site_filter=request.site_filter,
            model_name=request.model_name
        )
        
        # Log and return the response
        logger.info(f"Generated response for query: {request.query[:50]}...")
        
        return ChatResponse(
            response=response,
            sources=sources,
            query=request.query
        )
        
    except Exception as e:
        logger.error(f"Error processing query: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error processing query: {str(e)}"
        )

@app.get("/status", response_model=StatusResponse)
async def status():
    """Get the current status of the API"""
    global rag, crawl_task
    
    if not rag:
        return {
            "status": "initializing",
            "message": "SimGrag is still initializing"
        }
    
    if crawl_task and not crawl_task.done():
        return {
            "status": "crawling",
            "message": "Website crawling is in progress"
        }
    
    return {
        "status": "ready",
        "message": "Kenya Law Assistant is ready for queries"
    }

@app.post("/crawl", response_model=StatusResponse)
async def crawl(request: CrawlRequest, background_tasks: BackgroundTasks):
    """
    Start a crawl of the Kenya Law websites
    
    Args:
        request: Crawl request parameters
        background_tasks: FastAPI background tasks
        
    Returns:
        Status response
    """
    global rag, crawl_task
    
    # Check if SimGrag is initialized
    if not rag:
        raise HTTPException(status_code=503, detail="Service not yet initialized")
    
    # Check if a crawl is already in progress
    if crawl_task and not crawl_task.done():
        return {
            "status": "in_progress",
            "message": "A crawl is already in progress"
        }
    
    # Define the crawl function
    async def do_crawl():
        try:
            logger.info(f"Starting crawl with max_pages={request.max_pages}, max_depth={request.max_depth}")
            await rag.crawl_sites(
                max_pages=request.max_pages,
                max_depth=request.max_depth,
                resume=request.resume
            )
            logger.info("Crawl completed successfully")
        except Exception as e:
            logger.error(f"Crawl failed: {str(e)}")
    
    # Start the crawl in the background
    crawl_task = asyncio.create_task(do_crawl())
    
    return {
        "status": "started",
        "message": f"Started crawling with max_pages={request.max_pages}, max_depth={request.max_depth}"
    }

# Function to run the API server
def run_api(host: str = "0.0.0.0", port: int = 8000, reload: bool = False):
    """Run the FastAPI server"""
    uvicorn.run("api:app", host=host, port=port, reload=reload)

if __name__ == "__main__":
    import argparse
    
    # Set up command line arguments
    parser = argparse.ArgumentParser(description="Run the Kenya Law Assistant API")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host to bind the API server")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind the API server")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload (development mode)")
    
    args = parser.parse_args()
    
    # Ensure static directory exists
    static_dir = Path(__file__).parent / "static"
    static_dir.mkdir(exist_ok=True)
    
    # Run the API server
    run_api(host=args.host, port=args.port, reload=args.reload)