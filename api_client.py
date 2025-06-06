"""
API Client for Kenya Law Assistant: Provides a simple Python client to interact with the SimGrag API
"""
import requests
import argparse
import json
from typing import Dict, List, Any, Optional, Union
import logging
import sys

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class KenyaLawClient:
    """Client for interacting with the Kenya Law Assistant API"""
    
    def __init__(self, api_url: str = "http://localhost:8000"):
        """
        Initialize the Kenya Law API client
        
        Args:
            api_url: Base URL of the Kenya Law Assistant API
        """
        self.api_url = api_url.rstrip('/')
        logger.info(f"Initialized Kenya Law API client for {api_url}")
        
    def get_status(self) -> Dict[str, str]:
        """
        Get the current status of the API
        
        Returns:
            Status response as a dictionary
        """
        try:
            response = requests.get(f"{self.api_url}/status")
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error getting status: {str(e)}")
            return {"status": "error", "message": str(e)}
            
    def get_sample_questions(self) -> List[str]:
        """
        Get a list of sample questions
        
        Returns:
            List of sample questions
        """
        try:
            response = requests.get(f"{self.api_url}/sample-questions")
            response.raise_for_status()
            return response.json()["questions"]
        except Exception as e:
            logger.error(f"Error getting sample questions: {str(e)}")
            return []
            
    def ask(
        self, 
        query: str, 
        site_filter: Optional[str] = None, 
        model_name: str = "llama3"
    ) -> Dict[str, Any]:
        """
        Ask a question to the Kenya Law Assistant
        
        Args:
            query: The question to ask
            site_filter: Optional site filter (kenyalaw.org or new.kenyalaw.org)
            model_name: Model name to use with Ollama
            
        Returns:
            Response from the assistant
        """
        try:
            data = {
                "query": query,
                "model_name": model_name
            }
            
            if site_filter:
                data["site_filter"] = site_filter
                
            response = requests.post(
                f"{self.api_url}/chat", 
                json=data
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error asking question: {str(e)}")
            return {
                "response": f"Error: {str(e)}",
                "sources": [],
                "query": query
            }
            
    def start_crawl(
        self, 
        max_pages: int = 100, 
        max_depth: int = 3, 
        resume: bool = True
    ) -> Dict[str, str]:
        """
        Start a crawl job
        
        Args:
            max_pages: Maximum number of pages to crawl
            max_depth: Maximum depth of links to follow
            resume: Whether to resume from previous crawl
            
        Returns:
            Status response
        """
        try:
            data = {
                "max_pages": max_pages,
                "max_depth": max_depth,
                "resume": resume
            }
            
            response = requests.post(
                f"{self.api_url}/crawl", 
                json=data
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error starting crawl: {str(e)}")
            return {"status": "error", "message": str(e)}
            
    def print_response(self, response: Dict[str, Any]) -> None:
        """
        Pretty print a response from the API
        
        Args:
            response: Response from the API
        """
        if "response" not in response:
            print(json.dumps(response, indent=2))
            return
            
        print("\n" + "="*50)
        print(f"QUERY: {response['query']}")
        print("="*50)
        print("\nRESPONSE:")
        print(response["response"])
        
        if response.get("sources"):
            print("\nSOURCES:")
            for source in response["sources"]:
                title = source.get("title", "Untitled")
                url = source.get("url", "")
                print(f"- {title}: {url}")
        
        print("="*50)

def main():
    """Command-line interface for the Kenya Law API client"""
    parser = argparse.ArgumentParser(description="Kenya Law Assistant API Client")
    parser.add_argument("--url", type=str, default="http://localhost:8000", 
                        help="Base URL of the Kenya Law Assistant API")
    
    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    
    # Status command
    status_parser = subparsers.add_parser("status", help="Get API status")
    
    # Sample questions command
    questions_parser = subparsers.add_parser("questions", help="Get sample questions")
    
    # Ask command
    ask_parser = subparsers.add_parser("ask", help="Ask a question")
    ask_parser.add_argument("query", type=str, help="Question to ask")
    ask_parser.add_argument("--site", type=str, choices=["kenyalaw.org", "new.kenyalaw.org"],
                            help="Site filter")
    ask_parser.add_argument("--model", type=str, default="llama3", 
                            help="Model name to use with Ollama")
    
    # Crawl command
    crawl_parser = subparsers.add_parser("crawl", help="Start a crawl job")
    crawl_parser.add_argument("--pages", type=int, default=100, help="Maximum pages to crawl")
    crawl_parser.add_argument("--depth", type=int, default=3, help="Maximum depth to crawl")
    crawl_parser.add_argument("--no-resume", action="store_false", dest="resume", 
                              help="Don't resume from previous crawl")
    
    # Interactive command
    interactive_parser = subparsers.add_parser("interactive", help="Start interactive mode")
    interactive_parser.add_argument("--site", type=str, choices=["kenyalaw.org", "new.kenyalaw.org"],
                                  help="Site filter")
    interactive_parser.add_argument("--model", type=str, default="llama3", 
                                  help="Model name to use with Ollama")
    
    args = parser.parse_args()
    
    # Create client
    client = KenyaLawClient(api_url=args.url)
    
    # Process commands
    if args.command == "status":
        status = client.get_status()
        print(f"API Status: {status['status']}")
        print(f"Message: {status['message']}")
        
    elif args.command == "questions":
        questions = client.get_sample_questions()
        print("Sample Questions:")
        for i, question in enumerate(questions, 1):
            print(f"{i}. {question}")
            
    elif args.command == "ask":
        response = client.ask(
            query=args.query,
            site_filter=args.site,
            model_name=args.model
        )
        client.print_response(response)
        
    elif args.command == "crawl":
        status = client.start_crawl(
            max_pages=args.pages,
            max_depth=args.depth,
            resume=args.resume
        )
        print(f"Crawl Status: {status['status']}")
        print(f"Message: {status['message']}")
        
    elif args.command == "interactive":
        print("\n" + "="*50)
        print("Kenya Law Assistant Interactive Mode")
        print("="*50)
        print("Type 'exit', 'quit', or 'q' to end the session")
        print("Type 'help' to see available commands")
        print("="*50 + "\n")
        
        site_filter = args.site
        model_name = args.model
        
        while True:
            try:
                query = input("\nQuestion: ").strip()
                
                if query.lower() in ['exit', 'quit', 'q']:
                    print("Ending session. Goodbye!")
                    break
                    
                if query.lower() == 'help':
                    print("\nAvailable commands:")
                    print("  exit, quit, q - End the session")
                    print("  help - Show this help message")
                    print("  site:kenyalaw.org - Set site filter to kenyalaw.org")
                    print("  site:new.kenyalaw.org - Set site filter to new.kenyalaw.org")
                    print("  site:clear - Remove site filter")
                    print("  model:[name] - Change the model (e.g., model:mistral)")
                    print("  status - Check API status")
                    continue
                    
                if query.lower() == 'site:kenyalaw.org':
                    site_filter = 'kenyalaw.org'
                    print(f"Site filter set to: {site_filter}")
                    continue
                    
                if query.lower() == 'site:new.kenyalaw.org':
                    site_filter = 'new.kenyalaw.org'
                    print(f"Site filter set to: {site_filter}")
                    continue
                    
                if query.lower() == 'site:clear':
                    site_filter = None
                    print("Site filter cleared")
                    continue
                    
                if query.lower().startswith('model:'):
                    model_name = query.split(':', 1)[1].strip()
                    print(f"Model set to: {model_name}")
                    continue
                    
                if query.lower() == 'status':
                    status = client.get_status()
                    print(f"API Status: {status['status']}")
                    print(f"Message: {status['message']}")
                    continue
                    
                if not query:
                    continue
                    
                print("Thinking...")
                
                response = client.ask(
                    query=query,
                    site_filter=site_filter,
                    model_name=model_name
                )
                
                client.print_response(response)
                
            except KeyboardInterrupt:
                print("\nSession interrupted. Goodbye!")
                break
                
            except Exception as e:
                print(f"Error: {str(e)}")
                
    else:
        print("Please specify a command. Use --help for available commands.")
        sys.exit(1)

if __name__ == "__main__":
    main()