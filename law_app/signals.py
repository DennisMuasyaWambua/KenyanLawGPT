import logging
import os
from django.conf import settings
from django.dispatch import receiver
from django.db.models.signals import post_migrate

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

@receiver(post_migrate)
def initialize_simgrag(sender, **kwargs):
    """
    Initialize the SimGrag instance after Django has completed migrations
    """
    global rag
    
    if sender.name == 'law_app':
        logger.info("Initializing SimGrag instance...")
        
        # Get settings from Django settings
        vector_db_path = settings.VECTOR_DB_PATH
        concurrent_requests = settings.CONCURRENT_REQUESTS
        request_delay = settings.REQUEST_DELAY
        
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
