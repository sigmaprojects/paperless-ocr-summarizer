#!/bin/bash

# Paperless AI OCR Startup Script
# This script provides convenient ways to start the application

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Function to check if .env file exists
check_env_file() {
    if [ ! -f .env ]; then
        print_warning ".env file not found"
        if [ -f env.example ]; then
            print_status "Copying env.example to .env"
            cp env.example .env
            print_warning "Please edit .env file with your configuration before starting"
            return 1
        else
            print_error "No environment configuration found"
            return 1
        fi
    fi
    return 0
}

# Function to install Python dependencies
install_dependencies() {
    print_status "Installing Python dependencies..."
    if command_exists pip; then
        pip install -r requirements.txt
        print_success "Dependencies installed"
    else
        print_error "pip not found. Please install Python and pip first."
        exit 1
    fi
}

# Function to start the application in development mode
start_dev() {
    print_status "Starting Paperless AI OCR in development mode..."
    
    if ! check_env_file; then
        exit 1
    fi
    
    if [ ! -d "venv" ]; then
        print_status "Creating virtual environment..."
        python -m venv venv
    fi
    
    print_status "Activating virtual environment..."
    source venv/bin/activate
    
    install_dependencies
    
    print_status "Starting application..."
    python main.py
}

# Function to start with Docker
start_docker() {
    print_status "Starting Paperless AI OCR with Docker..."
    
    if ! command_exists docker; then
        print_error "Docker not found. Please install Docker first."
        exit 1
    fi
    
    if [ ! -f docker-compose.yml ]; then
        print_error "docker-compose.yml not found"
        exit 1
    fi
    
    print_status "Building and starting containers..."
    docker-compose up --build -d
    
    print_success "Application started in Docker"
    print_status "API available at: http://localhost:8574"
    print_status "Health check: http://localhost:8574/health"
    print_status "View logs: docker-compose logs -f"
}

# Function to stop Docker containers
stop_docker() {
    print_status "Stopping Docker containers..."
    docker-compose down
    print_success "Containers stopped"
}

# Function to show status
show_status() {
    print_status "Checking application status..."
    
    if command_exists python; then
        python cli.py --status
    else
        print_error "Python not found"
        exit 1
    fi
}

# Function to run CLI
run_cli() {
    shift # Remove the 'cli' argument
    
    if ! check_env_file; then
        exit 1
    fi
    
    if command_exists python; then
        python cli.py "$@"
    else
        print_error "Python not found"
        exit 1
    fi
}

# Function to show help
show_help() {
    echo "Paperless AI OCR Startup Script"
    echo ""
    echo "Usage: $0 [COMMAND]"
    echo ""
    echo "Commands:"
    echo "  dev              Start in development mode (local Python)"
    echo "  docker           Start with Docker Compose"
    echo "  stop             Stop Docker containers"
    echo "  status           Check application status"
    echo "  cli [ARGS]       Run CLI with arguments"
    echo "  help             Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 dev                           # Start in development mode"
    echo "  $0 docker                        # Start with Docker"
    echo "  $0 cli --status                  # Check status via CLI"
    echo "  $0 cli --document-id 123         # Process specific document"
    echo "  $0 cli --auto-discover           # Process next document"
    echo ""
}

# Main script logic
case "${1:-help}" in
    dev)
        start_dev
        ;;
    docker)
        start_docker
        ;;
    stop)
        stop_docker
        ;;
    status)
        show_status
        ;;
    cli)
        run_cli "$@"
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        print_error "Unknown command: $1"
        show_help
        exit 1
        ;;
esac 