# Kenya Law Assistant API

A FastAPI-based API that provides access to a Kenya Law chatbot powered by RAG (Retrieval-Augmented Generation).

## Overview

This project provides:

1. A web crawler that indexes Kenya Law website content
2. Vector database storage of indexed content
3. A chatbot that can answer questions using the indexed content
4. A REST API to interact with the chatbot
5. A simple web interface to use the chatbot
6. A Python client for programmatic access

## Requirements

See `requirements.txt` for a full list of dependencies.

Main components:
- FastAPI
- Sentence Transformers
- ChromaDB
- Ollama (for LLM inference)

## Setup and Usage

### Installation

1. Clone the repository
2. Create a virtual environment: `python -m venv venv`
3. Activate the virtual environment:
   - Linux/Mac: `source venv/bin/activate`
   - Windows: `venv\Scripts\activate`
4. Install dependencies: `pip install -r requirements.txt`

### Running the API

```bash
# Start the API server
python api.py --port 8000

# Enable development mode with auto-reload
python api.py --port 8000 --reload
```

### API Endpoints

- `GET /`: Web interface for the chatbot
- `GET /api`: Check if API is running
- `GET /status`: Check service status
- `GET /sample-questions`: Get sample legal questions
- `POST /chat`: Send a query to the chatbot
- `POST /crawl`: Start a new crawl job

## Using the API Client

The project includes a Python client for easy API access:

```python
from api_client import KenyaLawClient

# Create client
client = KenyaLawClient(api_url="http://localhost:8000")

# Get API status
status = client.get_status()
print(f"API Status: {status['status']}")

# Ask a legal question
response = client.ask(
    query="What are the key provisions of the Land Registration Act?",
    site_filter="kenyalaw.org",  # Optional
    model_name="llama3"          # Optional
)

# Print response
print(response["response"])

# Access sources
for source in response["sources"]:
    print(f"- {source['title']}: {source['url']}")
```

### Command Line Interface

The client also provides a command-line interface:

```bash
# Check API status
python api_client.py status

# Get sample questions
python api_client.py questions

# Ask a question
python api_client.py ask "What are the key provisions of the Land Registration Act?"

# Ask with site filter
python api_client.py ask "What are the key provisions of the Land Registration Act?" --site kenyalaw.org

# Start a crawl
python api_client.py crawl --pages 200 --depth 5

# Interactive mode
python api_client.py interactive
```

## Using SimGrag for Complex Legal Research

The SimGrag system is designed for thorough legal research in Kenya's legal corpus. Here's how to use it effectively:

### Getting Started with SimGrag

1. **Direct Command-Line Access**:
   ```bash
   python law.py --use-simgrag --no-crawl --query "Explain the key provisions of the Land Registration Act"
   ```

2. **Interactive Mode**:
   ```bash
   python law.py --use-simgrag --no-crawl
   ```

3. **Via the API**:
   Visit http://localhost:8000 after starting the server with `python api.py`

4. **Via the Python Client**:
   ```bash
   python api_client.py interactive
   ```

### Advanced Research Techniques

1. **Site-Specific Searches**:
   - Use the `site_filter` parameter to target kenyalaw.org or new.kenyalaw.org
   - In CLI: `--site-filter kenyalaw.org`
   - In API: Select from dropdown menu
   - In client: `client.ask(query="...", site_filter="kenyalaw.org")`

2. **Multi-step Research**:
   - Start with broad questions to understand the legal framework
   - Follow up with specific questions about sections, cases, or interpretations
   - Use previous answers to formulate more targeted follow-up questions

3. **Finding Related Case Law**:
   - Ask for specific cases that relate to your legal topic
   - Request interpretations of specific sections by courts
   - Example: "What cases have interpreted Section 24 of the Land Registration Act?"

4. **Comparing Legal Interpretations**:
   - Ask how different courts have interpreted the same legal provision
   - Example: "How have High Court and Court of Appeal interpreted fair trial rights?"

5. **Technical Legal Research**:
   - For legal professionals, use precise legal terminology
   - Reference specific sections, acts, and legal doctrines
   - Example: "Explain the doctrine of adverse possession under Kenyan land law"

### Programmatic API Usage for Research

For researchers and developers, the Python client enables automation of complex research:

```python
import asyncio
from api_client import KenyaLawClient

async def research_project():
    client = KenyaLawClient()
    
    # Phase 1: Broad understanding
    overview = client.ask("What is the structure of intellectual property law in Kenya?")
    
    # Phase 2: Specific acts analysis
    copyright_act = client.ask("Explain the key provisions of the Copyright Act in Kenya")
    trademarks_act = client.ask("Explain the key provisions of the Trademarks Act in Kenya")
    
    # Phase 3: Case law research
    cases = client.ask("What are landmark cases in Kenyan intellectual property law?")
    
    # Save results
    with open("ip_law_research.txt", "w") as f:
        f.write("# Overview of Kenyan IP Law\n\n")
        f.write(overview["response"])
        f.write("\n\n# Copyright Act Analysis\n\n")
        f.write(copyright_act["response"])
        f.write("\n\n# Trademarks Act Analysis\n\n")
        f.write(trademarks_act["response"])
        f.write("\n\n# Landmark Cases\n\n")
        f.write(cases["response"])

# Run the research
if __name__ == "__main__":
    asyncio.run(research_project())
```

### Crawling Configuration

For thorough research, you may need comprehensive data:

```bash
# Full comprehensive crawl
python law.py --use-simgrag --pages 1000 --depth 7 --concurrent 4 --delay 1.0

# Focused crawl on specific legal areas
python law.py --use-simgrag --pages 500 --depth 5 --ollama llama3
```

### Tips for Best Results

1. Be specific in your questions
2. Use legal terminology when possible
3. For complex topics, break down into several specific questions
4. Use the site filtering to target the most relevant database
5. Verify important information against primary sources
6. Structure multi-part questions clearly with numbered points

## LLM Integration

The system is designed to work with Ollama, an easy-to-use local LLM server.
To use with Ollama:

1. Install Ollama from https://ollama.ai/
2. Pull a model: `ollama pull llama3`
3. Start Ollama
4. The API will automatically connect to the Ollama server

## License

[MIT License](LICENSE)