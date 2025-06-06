# Deploying Kenya Law Assistant on Railway

This guide walks you through deploying the Kenya Law Assistant API to Railway.

## Prerequisites

1. A Railway account (sign up at https://railway.app)
2. Git repository with your code
3. Railway CLI (optional)

## Deployment Steps

### Option 1: Deploy via Railway Dashboard

1. **Log in to Railway**:
   - Go to https://railway.app and log in with your account

2. **Create a New Project**:
   - Click "New Project"
   - Select "Deploy from GitHub repo"
   - Connect your GitHub account if not already connected
   - Select your repository

3. **Configure Environment Variables**:
   - Go to the "Variables" tab in your project
   - Add the following environment variables:
     - `VECTOR_DB_PATH`: `./data/vector_db` (or your preferred path)
     - `PORT`: `8000` (Railway will set this automatically, but good to have)
     - `CONCURRENT_REQUESTS`: `4`
     - `REQUEST_DELAY`: `1.0`

4. **Configure Volumes (Optional, Recommended)**:
   - Go to the "Volumes" tab
   - Create a new volume of at least 1GB
   - Mount it at `/app/data`
   - This will persist your vector database between deployments

5. **Deploy**:
   - Railway will automatically build and deploy your application
   - You can find the URL to your deployed API in the "Settings" tab

### Option 2: Deploy via Railway CLI

1. **Install Railway CLI**:
   ```bash
   npm i -g @railway/cli
   ```

2. **Login to Railway**:
   ```bash
   railway login
   ```

3. **Initialize a new project**:
   ```bash
   railway init
   ```

4. **Add environment variables**:
   ```bash
   railway variables set VECTOR_DB_PATH=./data/vector_db
   railway variables set CONCURRENT_REQUESTS=4
   railway variables set REQUEST_DELAY=1.0
   ```

5. **Deploy**:
   ```bash
   railway up
   ```

## After Deployment

1. **Initiate a Crawl**:
   Once deployed, visit your API endpoint (e.g., https://your-app-name.railway.app) and start a crawl:
   ```bash
   curl -X POST https://your-app-name.railway.app/crawl \
     -H "Content-Type: application/json" \
     -d '{"max_pages": 100, "max_depth": 3, "resume": true}'
   ```

2. **Test the API**:
   ```bash
   curl -X POST https://your-app-name.railway.app/chat \
     -H "Content-Type: application/json" \
     -d '{"query": "What is the Kenyan Constitution?", "site_filter": null, "model_name": "llama3"}'
   ```

3. **Access the Web Interface**:
   - Open your browser and go to your Railway app URL (e.g., https://your-app-name.railway.app)

## Troubleshooting

- **Memory Issues**: If you encounter memory problems, adjust the CONCURRENT_REQUESTS to a lower value
- **Cold Start**: The first request after deployment might be slow due to model loading
- **Log Monitoring**: Check the Railway logs for any issues
- **Ollama Configuration**: Ensure Ollama access works in the Railway environment

## Scaling Considerations

1. **Database Size**: 
   - The vector database can grow large with extensive crawling
   - Consider using a separate persistent storage solution for production

2. **Compute Resources**:
   - Railway offers different instance sizes
   - For production use, you may need to scale up from the default instance

3. **API Rate Limiting**:
   - Consider implementing rate limiting for public-facing deployments

## Notes on Railway Deployment

- Railway automatically assigns a PORT, which is accessible via the PORT environment variable
- Railway instances are ephemeral by default, so use volumes for persistence
- Railway automatically handles HTTPS for your deployment