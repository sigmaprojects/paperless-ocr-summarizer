# Paperless AI OCR

An AI-powered OCR and summarization service for Paperless-NGX documents using Ollama vision models.

This tool was developed 95% by claude-4-sonnet in Cursor.  I just wanted a way to get more accurate OCR than what Tesseract was doing.
Since the Paperless api doesn't currently offer a way to change the Content field of a document, this adds a note with the AI OCR contents and summary.  Note contents are included while searching in the Paperless webui.

## Features

- **Automated Document Processing**: Automatically discovers and processes documents without the "summarized" tag
- **OCR Extraction**: Uses Ollama vision models to extract text from PDF documents
- **AI Summarization**: Generates intelligent summaries of document content
- **Job Management**: Full job lifecycle management with status tracking
- **REST API**: Complete REST API for integration and monitoring
- **Async Processing**: Non-blocking document processing with progress tracking
- **File Storage**: Temporary storage of OCR and summary results
- **Paperless Integration**: Seamless integration with Paperless-NGX API

## Requirements

- Python 3.8+
- Running Paperless-NGX instance
- Running Ollama instance with a vision model (e.g., minicpm-v, moondream)
- Docker (optional, for containerized deployment)

## Installation

### Local Development

1. **Clone the repository**:
   ```bash
   git clone <repository-url>
   cd paperless-ai-ocr
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure environment**:
   ```bash
   cp env.example .env
   # Edit .env with your actual configuration
   ```

4. **Run the application**:
   ```bash
   python main.py
   ```

### Docker Deployment

1. **Build the image**:
   ```bash
   docker build -t paperless-ai-ocr .
   ```

2. **Run with docker-compose**:
   ```bash
   docker-compose up -d
   ```

## Configuration

All configuration is done through environment variables. See `env.example` for all available options.

### Required Configuration

- `PAPERLESS_BASE_URL`: URL of your Paperless-NGX instance
- `PAPERLESS_TOKEN`: API token for Paperless-NGX access
- `OLLAMA_BASE_URL`: URL of your Ollama instance
- `OLLAMA_MODEL`: Ollama vision model to use (e.g., `minicpm-v:latest`, `moondream:latest`)

### Optional Configuration

- `SUMMARIZED_TAG`: Tag name to mark processed documents (default: "summarized")
- `DATA_DIR`: Directory for temporary file storage (default: "./data")
- `MAX_CONCURRENT_JOBS`: Maximum concurrent processing jobs (default: 1)
- `JOB_TIMEOUT_SECONDS`: Timeout for individual jobs (default: 3600)
- `API_HOST`: API server host (default: "0.0.0.0")
- `API_PORT`: API server port (default: 8574)

## API Usage

### Health Check

```bash
GET /health
```

Returns the health status of the application and connected services.

### Create Job

```bash
POST /jobs
Content-Type: application/json

{
  "document_id": 123,          # Optional: specific document ID
  "auto_discover": true        # Optional: auto-discover documents (default: true)
}
```

Creates a new document processing job. If `document_id` is provided, processes that specific document. Otherwise, auto-discovers the next document without the summarized tag.

### List Jobs

```bash
GET /jobs
```

Returns all processing jobs with their current status.

### Get Job Status

```bash
GET /jobs/{job_id}
```

Returns detailed information about a specific job. Note: `job_id` matches the `document_id` for easy tracking.

### Cancel Job

```bash
POST /jobs/{job_id}/cancel
```

Cancels a running job.

### Remove Job

```bash
DELETE /jobs/{job_id}
```

Removes a completed job and cleans up associated files.

## CLI Usage

You can also use the application via command line:

```bash
# Process a specific document
python cli.py --document-id 123

# Auto-discover and process next document
python cli.py --auto-discover

# Check application status
python cli.py --status
```

## How It Works

1. **Document Discovery**: The application queries Paperless-NGX for documents that don't have the configured "summarized" tag
2. **PDF Download**: Downloads the PDF file from Paperless-NGX
3. **AI Processing**: Sends the PDF to Ollama vision model for OCR extraction and summarization
4. **File Storage**: Saves OCR and summary results to text files named `{document_id}_ocr.txt` and `{document_id}_summary.txt`
5. **Paperless Upload**: Adds a note to the original document containing the summary and OCR content
6. **Tagging**: Adds the "summarized" tag to mark the document as processed

## Job States

- **PENDING**: Job created, waiting to start
- **DOWNLOADING**: Downloading PDF from Paperless
- **PROCESSING**: Processing with Ollama AI
- **UPLOADING**: Uploading results back to Paperless
- **COMPLETED**: Successfully completed
- **FAILED**: Processing failed
- **CANCELLED**: Cancelled by user

## Docker Support

The application is designed to run in Docker containers. The included `Dockerfile` and `docker-compose.yml` provide easy deployment options.

### Environment Variables in Docker

When using Docker, mount a `.env` file or pass environment variables directly:

```bash
docker run -d \
  --name paperless-ai-ocr \
  -p 8574:8574 \
  -e PAPERLESS_BASE_URL=http://paperless:8000 \
  -e PAPERLESS_TOKEN=your_token \
  -e OLLAMA_BASE_URL=http://ollama:11434 \
  -e OLLAMA_MODEL=moondream:latest \
  paperless-ai-ocr
```

## Monitoring and Logging

The application provides structured logging and health endpoints for monitoring:

- Logs are written to stdout in a structured format
- Health endpoint at `/health` provides service status
- Job status tracking with timing information
- Error handling with detailed error messages

## Troubleshooting

### Common Issues

1. **Connection errors**: Verify Paperless and Ollama URLs are accessible
2. **Authentication errors**: Check Paperless API token is valid
3. **Model errors**: Ensure the specified Ollama model is installed and available
4. **Processing timeouts**: Increase `JOB_TIMEOUT_SECONDS` for large documents
5. **File permission errors**: Ensure the `DATA_DIR` is writable

### Debug Mode

Set logging level to DEBUG for verbose output:

```bash
export LOG_LEVEL=DEBUG
python main.py
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details. 