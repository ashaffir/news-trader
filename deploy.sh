#!/bin/bash

# Production Deployment Script
# This script handles the deployment process on the production server
# It can be run manually or via GitHub Actions

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging function
log() {
    echo -e "${BLUE}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1" >&2
}

success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

# Check if we're in the right directory
if [ ! -f "manage.py" ] || [ ! -f "docker-compose.yml" ]; then
    error "This script must be run from the news-trader project root directory"
    exit 1
fi

# Backup current state (optional but recommended)
backup_current_state() {
    log "Creating backup of current Docker volumes..."
    docker-compose exec -T db pg_dump -U news_trader news_trader > "backup_$(date +%Y%m%d_%H%M%S).sql" || true
}

# Pull latest code
update_code() {
    log "Pulling latest code from Git..."
    git fetch origin
    local current_commit=$(git rev-parse HEAD)
    git reset --hard origin/main
    local new_commit=$(git rev-parse HEAD)
    
    if [ "$current_commit" = "$new_commit" ]; then
        warning "No new commits to deploy"
        return 1
    else
        success "Updated to commit: $new_commit"
        return 0
    fi
}

# Stop services gracefully
stop_services() {
    log "Stopping services gracefully..."
    docker-compose down --timeout 30
    
    # Wait a moment for complete shutdown
    sleep 5
    
    # Verify all containers are stopped
    if [ "$(docker-compose ps -q)" ]; then
        warning "Some containers still running, forcing stop..."
        docker-compose down --timeout 10
    fi
}

# Build updated images
build_images() {
    log "Building updated Docker images..."
    docker-compose build --no-cache
    
    if [ $? -ne 0 ]; then
        error "Docker build failed"
        exit 1
    fi
}

# Run database migrations
run_migrations() {
    log "Running database migrations..."
    
    # Start only the database service first
    docker-compose up -d db redis
    sleep 10
    
    # Run migrations
    docker-compose run --rm web python manage.py migrate
    
    if [ $? -ne 0 ]; then
        error "Database migrations failed"
        exit 1
    fi
}

# Collect static files
collect_static() {
    log "Collecting static files..."
    docker-compose run --rm web python manage.py collectstatic --noinput
    
    if [ $? -ne 0 ]; then
        error "Static file collection failed"
        exit 1
    fi
}

# Start all services
start_services() {
    log "Starting all services..."
    docker-compose up -d
    
    if [ $? -ne 0 ]; then
        error "Failed to start services"
        exit 1
    fi
}

# Health check
health_check() {
    log "Performing health checks..."
    
    local max_attempts=12
    local attempt=1
    
    while [ $attempt -le $max_attempts ]; do
        log "Health check attempt $attempt/$max_attempts..."
        
        # Check if containers are running
        if ! docker-compose ps | grep -q "Up"; then
            error "Some containers are not running"
            docker-compose ps
            return 1
        fi
        
        # Check web service health endpoint
        if curl -f -s http://localhost:8800/health/ >/dev/null 2>&1; then
            success "Health check passed!"
            return 0
        fi
        
        if [ $attempt -eq $max_attempts ]; then
            error "Health check failed after $max_attempts attempts"
            show_debug_info
            return 1
        fi
        
        log "Waiting 10 seconds before next attempt..."
        sleep 10
        ((attempt++))
    done
}

# Show debug information on failure
show_debug_info() {
    error "Deployment failed. Debug information:"
    echo
    echo "=== Container Status ==="
    docker-compose ps
    echo
    echo "=== Web Service Logs (last 30 lines) ==="
    docker-compose logs --tail=30 web
    echo
    echo "=== Celery Service Logs (last 20 lines) ==="
    docker-compose logs --tail=20 celery
}

# Main deployment function
deploy() {
    log "🚀 Starting deployment process..."
    
    # Create backup (comment out if not needed)
    # backup_current_state
    
    # Update code (skip if no changes)
    if ! update_code; then
        success "No deployment needed - already up to date"
        exit 0
    fi
    
    # Stop services
    stop_services
    
    # Build new images
    build_images
    
    # Run migrations
    run_migrations
    
    # Collect static files
    collect_static
    
    # Start services
    start_services
    
    # Health check
    if health_check; then
        success "🎉 Deployment completed successfully!"
        log "Services are now running with the latest code"
        
        # Show service status
        echo
        docker-compose ps
    else
        error "❌ Deployment failed during health check"
        exit 1
    fi
}

# Rollback function (for manual use)
rollback() {
    log "🔄 Rolling back to previous commit..."
    git reset --hard HEAD~1
    stop_services
    build_images
    run_migrations
    collect_static
    start_services
    health_check
}

# Show usage
usage() {
    echo "Usage: $0 [deploy|rollback|health]"
    echo "  deploy   - Deploy latest code (default)"
    echo "  rollback - Rollback to previous commit"
    echo "  health   - Run health check only"
    exit 1
}

# Main script logic
case "${1:-deploy}" in
    deploy)
        deploy
        ;;
    rollback)
        rollback
        ;;
    health)
        health_check
        ;;
    *)
        usage
        ;;
esac
