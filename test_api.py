#!/usr/bin/env python
"""
Test script for Kenya Law Assistant API
This script verifies that the RAG functionality is working properly
"""
import requests
import os
import sys
import time
import json
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# API URL
API_URL = "http://localhost:8000"

def test_status():
    """Test the status endpoint"""
    try:
        response = requests.get(f"{API_URL}/api/status/")
        response.raise_for_status()
        data = response.json()
        logger.info(f"Status: {data['status']}")
        logger.info(f"Message: {data['message']}")
        return data
    except Exception as e:
        logger.error(f"Error testing status: {str(e)}")
        return None

def test_sample_questions():
    """Test the sample questions endpoint"""
    try:
        response = requests.get(f"{API_URL}/api/sample-questions/")
        response.raise_for_status()
        data = response.json()
        logger.info(f"Got {len(data['questions'])} sample questions")
        for i, question in enumerate(data['questions'][:2], 1):
            logger.info(f"Sample {i}: {question}")
        return data
    except Exception as e:
        logger.error(f"Error testing sample questions: {str(e)}")
        return None

def test_chat(query="What is the Kenya Constitution?", site_filter=None, model_name="llama3"):
    """Test the chat endpoint"""
    try:
        data = {
            "query": query,
            "model_name": model_name
        }
        
        if site_filter:
            data["site_filter"] = site_filter
        
        logger.info(f"Testing chat with query: '{query}'")
        
        response = requests.post(f"{API_URL}/api/chat/", json=data)
        response.raise_for_status()
        result = response.json()
        
        logger.info(f"Query: {result['query']}")
        logger.info(f"Response (first 100 chars): {result['response'][:100]}...")
        
        if result.get('sources'):
            logger.info(f"Sources count: {len(result['sources'])}")
            for i, source in enumerate(result['sources'][:2], 1):
                logger.info(f"Source {i}: {source.get('title', 'Untitled')} - {source.get('url', 'No URL')}")
        
        return result
    except Exception as e:
        logger.error(f"Error testing chat: {str(e)}")
        return None

def main():
    """Main function"""
    logger.info("Starting API tests")
    
    # Wait for API to be ready
    max_retries = 3
    retries = 0
    while retries < max_retries:
        status = test_status()
        if status and status.get('status') in ['ready', 'initializing', 'crawling']:
            logger.info(f"API is {status.get('status')}")
            break
        
        logger.warning(f"API not responding properly, retrying ({retries+1}/{max_retries})...")
        retries += 1
        time.sleep(5)
    
    if retries == max_retries:
        logger.error("Could not connect to API after multiple attempts")
        sys.exit(1)
    
    # Test sample questions
    test_sample_questions()
    
    # Test chat
    test_chat()
    
    # Test chat with site filter
    test_chat(query="What is the Kenya Constitution?", site_filter="kenyalaw.org")
    
    logger.info("API tests completed successfully")

if __name__ == "__main__":
    main()