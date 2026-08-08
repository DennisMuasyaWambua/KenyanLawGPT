import logging
import os
from django.conf import settings
from django.dispatch import receiver
from django.db.models.signals import post_migrate
from dotenv import load_dotenv

# Load environment variables from .env file at initialization time
# This ensures environment variables are available before Django fully loads
load_dotenv()

# Log the OLLAMA_HOST value for debugging
ollama_host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
print(f"OLLAMA_HOST value during signals.py load: {ollama_host}")

# Import the chatbot components
from law import SimGrag

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# File handler to save logs to disk
file_handler = logging.FileHandler("django_law.log")
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(file_handler)

# Global SimGrag instance
rag = None

def init_rag():
    """
    Initialize the global SimGrag instance. Safe to call multiple times.
    """
    global rag

    if rag is None:
        logger.info("Initializing SimGrag instance...")
        
        # Get settings from Django settings or environment variables
        vector_db_path = settings.VECTOR_DB_PATH
        concurrent_requests = settings.CONCURRENT_REQUESTS
        request_delay = settings.REQUEST_DELAY
        
        # Create vector_db directory if it doesn't exist
        os.makedirs(vector_db_path, exist_ok=True)
        
        try:
            # Log Ollama host configuration to ensure it's being properly loaded
            ollama_host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
            logger.info(f"Using Ollama host for RAG: {ollama_host}")
            
            # Initialize SimGrag for both Kenya Law sites
            rag = SimGrag(
                vector_db_path=vector_db_path,
                chunk_size=1000,
                chunk_overlap=200,
                context_limit=4000,
                max_context_chunks=10
            )
            
            # Initialize vectorizers with robust error handling
            try:
                rag.initialize_vectorizers(
                    concurrent_requests=concurrent_requests,  # Conservative to avoid overwhelming the server
                    request_delay=request_delay               # Conservative delay
                )
                logger.info("Vectorizers initialized successfully")
            except Exception as vec_error:
                logger.error(f"Error initializing vectorizers, but continuing: {str(vec_error)}")
                # We don't set rag to None here, as partial initialization can still work
            
            logger.info(f"SimGrag initialization complete. Using vector_db_path={vector_db_path}")
        except Exception as e:
            logger.error(f"Error initializing SimGrag: {str(e)}")
            rag = None  # Ensure rag is None on error


@receiver(post_migrate)
def initialize_simgrag(sender, **kwargs):
    """
    Initialize the SimGrag instance after Django has completed migrations
    """
    # Skip the expensive model load when running the test suite (post_migrate
    # fires for the throwaway test database); tests patch the RAG seam instead.
    import sys
    if 'test' in sys.argv:
        return
    if sender.name == 'law_app':
        init_rag()
