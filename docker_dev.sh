#!/bin/bash

# News Trader Docker Development Manager
# Interactive Docker-based development environment

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Print functions
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

# Function to check if .env file exists
check_env_file() {
    if [ ! -f .env ]; then
        print_error ".env file not found!"
        echo "Please create a .env file with your configuration before running Docker."
        exit 1
    fi
}

# Function to check if Docker is running
check_docker() {
    if ! docker info >/dev/null 2>&1; then
        print_error "Docker is not running or not accessible!"
        echo "Please start Docker Desktop or Docker daemon first."
        exit 1
    fi
}

# Function to check service health
check_service_health() {
    local service_name=$1
    local url=$2
    local timeout=${3:-5}
    
    if curl -s --max-time "$timeout" "$url" >/dev/null 2>&1; then
        return 0
    else
        return 1
    fi
}

# Function to show Docker service status
show_docker_status() {
    echo -e "${BLUE}🐳 Docker Service Status:${NC}"
    echo "=========================="
    
    # Check if services are running
	local services=("web" "db" "redis" "celery" "celery-beat" "telegram-bot")
	local service_names=("Web App" "PostgreSQL" "Redis" "Celery Worker" "Celery Beat" "Telegram Bot")
    local running_count=0
    local i=0
    
    for service in "${services[@]}"; do
        if docker-compose ps "$service" 2>/dev/null | grep -q "Up"; then
            local container_id=$(docker-compose ps -q "$service" 2>/dev/null)
            if [ -n "$container_id" ]; then
                echo -e "  ${GREEN}✓${NC} ${service_names[$i]} (${container_id:0:12})"
                running_count=$((running_count + 1))
            else
                echo -e "  ${RED}✗${NC} ${service_names[$i]}"
            fi
        else
            echo -e "  ${RED}✗${NC} ${service_names[$i]}"
        fi
        i=$((i + 1))
    done
    
    # Check if Flower is running
    if docker-compose ps flower 2>/dev/null | grep -q "Up"; then
        echo -e "  ${GREEN}✓${NC} Flower Monitor"
    else
        echo -e "  ${YELLOW}○${NC} Flower Monitor (optional)"
    fi
    
    echo
    echo -e "${BLUE}🔍 Health Checks:${NC}"
    echo "=================="
    
    # Check web service health
    if check_service_health "Web App" "http://localhost:8800/health/" 3; then
        echo -e "  ${GREEN}✓${NC} Web App (http://localhost:8800)"
    else
        echo -e "  ${RED}✗${NC} Web App (not responding)"
    fi
    
    # Check database
    if docker-compose exec -T db pg_isready -U news_trader >/dev/null 2>&1; then
        echo -e "  ${GREEN}✓${NC} PostgreSQL Database"
    else
        echo -e "  ${RED}✗${NC} PostgreSQL Database"
    fi
    
    # Check Redis
    if docker-compose exec -T redis redis-cli ping >/dev/null 2>&1; then
        echo -e "  ${GREEN}✓${NC} Redis Cache"
    else
        echo -e "  ${RED}✗${NC} Redis Cache"
    fi
    
    # Check if flower is accessible
    if docker-compose ps flower 2>/dev/null | grep -q "Up"; then
        if check_service_health "Flower" "http://localhost:5555" 3; then
            echo -e "  ${GREEN}✓${NC} Flower Monitor (http://localhost:5555)"
        else
            echo -e "  ${YELLOW}⚠${NC} Flower Monitor (running but not accessible)"
        fi
    fi
    
    echo
    if [ $running_count -eq ${#services[@]} ]; then
        echo -e "  ${GREEN}🎉 All core services running!${NC}"
        echo -e "  ${BLUE}🌐 Web App: http://localhost:8800${NC}"
        echo -e "  ${BLUE}⚙️  Admin: http://localhost:8800/admin/${NC}"
        echo -e "  ${BLUE}🌸 Flower: http://localhost:5555${NC} (if started)"
    elif [ $running_count -gt 0 ]; then
        echo -e "  ${YELLOW}⚠️  $running_count of ${#services[@]} core services running${NC}"
    else
        echo -e "  ${RED}❌ No services running${NC}"
        echo -e "  ${YELLOW}💡 Use 'setup' for first time or 'start' to begin${NC}"
    fi
}

# Install Playwright browsers in containers
docker_playwright_install() {
    print_status "🎭 Installing Playwright Chromium in containers..."
    set +e
    # Use a cache dir writable by non-root user inside container
    docker-compose exec -T web bash -lc 'export PLAYWRIGHT_BROWSERS_PATH=/app/.cache/ms-playwright; mkdir -p "$PLAYWRIGHT_BROWSERS_PATH" && python -m playwright install chromium' &&
    docker-compose exec -T celery bash -lc 'export PLAYWRIGHT_BROWSERS_PATH=/app/.cache/ms-playwright; mkdir -p "$PLAYWRIGHT_BROWSERS_PATH" && python -m playwright install chromium'
    local rc=$?
    set -e
    if [ $rc -eq 0 ]; then
        print_success "✅ Playwright Chromium installed (web, celery)"
    else
        print_warning "⚠️ Playwright install reported issues. You can retry with: $0 pwinstall"
    fi
}

# Function to clean up failed setup
cleanup_failed_setup() {
    print_warning "🧹 Cleaning up failed setup..."
    docker-compose down -v 2>/dev/null || true
    docker system prune -f 2>/dev/null || true
    print_status "✅ Cleanup completed"
}

# Function to wait for database with timeout
wait_for_database() {
    local max_attempts=30
    local attempt=1
    
    print_status "⏳ Waiting for database to be ready..."
    
    while [ $attempt -le $max_attempts ]; do
        if docker-compose exec -T db pg_isready -U news_trader >/dev/null 2>&1; then
            print_success "✅ Database is ready!"
            return 0
        fi
        
        echo -n "."
        sleep 2
        attempt=$((attempt + 1))
    done
    
    print_error "❌ Database failed to start within timeout"
    return 1
}

# Function to setup (improved with error handling)
docker_setup() {
    print_status "🚀 Docker setup (robust with error recovery)..."
    
    # Disable exit on error for this function
    set +e
    local setup_failed=false
    
    # Check prerequisites
    if ! check_env_file || ! check_docker; then
        print_error "❌ Prerequisites not met"
        set -e
        return 1
    fi
    
    # Step 1: Clean any existing setup
    print_status "🧹 Cleaning any existing containers..."
    docker-compose down -v >/dev/null 2>&1 || true
    
    # Step 2: Build Docker images
    print_status "🏗️ Building Docker images..."
    if ! docker-compose build; then
        print_error "❌ Failed to build Docker images"
        setup_failed=true
    fi
    
    if [ "$setup_failed" = false ]; then
        # Step 3: Start database and Redis
        print_status "🗄️ Starting database and Redis..."
        if ! docker-compose up -d db redis; then
            print_error "❌ Failed to start database and Redis"
            setup_failed=true
        fi
    fi
    
    if [ "$setup_failed" = false ]; then
        # Step 4: Wait for database to be ready
        if ! wait_for_database; then
            print_error "❌ Database failed to become ready"
            setup_failed=true
        fi
    fi
    
    if [ "$setup_failed" = false ]; then
        # Step 5: Run database migrations
        print_status "📊 Running database migrations..."
        if ! docker-compose run --rm web python manage.py migrate; then
            print_error "❌ Failed to run database migrations"
            setup_failed=true
        fi
    fi
    
    if [ "$setup_failed" = false ]; then
        # Step 6: Collect static files
        print_status "📁 Collecting static files..."
        if ! docker-compose run --rm web python manage.py collectstatic --noinput; then
            print_warning "⚠️ Failed to collect static files (continuing anyway...)"
        fi
    fi
    
    if [ "$setup_failed" = false ]; then
        # Step 7: Start all services
        print_status "🚀 Starting all services..."
        if ! docker-compose up -d; then
            print_error "❌ Failed to start all services"
            setup_failed=true
        fi
    fi
    
    # Check if setup failed
    if [ "$setup_failed" = true ]; then
        print_error "❌ Setup failed!"
        echo ""
        print_status "🔧 Troubleshooting options:"
        echo "  1. Run 'cleanup' to clean everything and try again"
        echo "  2. Check your .env file has all required variables"
        echo "  3. Ensure Docker has enough resources (2GB+ RAM)"
        echo "  4. Check Docker logs: docker-compose logs"
        echo ""
        cleanup_failed_setup
        set -e
        return 1
    fi
    
    # Finalize runtime dependencies (Playwright)
    if [ "$setup_failed" = false ]; then
        docker_playwright_install
    fi

    # Final health check
    print_status "🔍 Performing final health check..."
    sleep 5
    
    if curl -sf http://localhost:8800/health/ >/dev/null 2>&1; then
        print_success "🎉 Setup completed successfully!"
        echo ""
        print_success "🌐 Web App: http://localhost:8800/dashboard/"
        print_success "⚙️  Admin Panel: http://localhost:8800/admin/"
        print_success "❤️  Health Check: http://localhost:8800/health/"
        print_success "🌸 Flower Monitor: http://localhost:5555 (use monitor option)"
        echo ""
        print_status "💡 Your News Trader is ready for testing!"
        print_status "💡 Default admin credentials: admin/admin"
    else
        print_warning "⚠️ Services started but health check failed"
        print_status "🔍 Check service status with: ./docker_dev.sh status"
        print_status "📋 Check logs with: ./docker_dev.sh logs"
    fi
    
    # Re-enable exit on error
    set -e
    return 0
}

# Function to start services
docker_start() {
    print_status "🚀 Starting all Docker services..."
    check_env_file
    check_docker
    # Start core dependencies first
    docker-compose up -d db redis
    wait_for_database || true
    # Start web and workers
    docker-compose up -d web celery celery-beat
    # Ensure Telegram bot is a single instance
    docker-compose up -d --scale telegram-bot=1 telegram-bot
    # Ensure Playwright browsers are installed
    docker_playwright_install || true
    sleep 3
    print_success "✅ Services started"
}

# Function to stop services
docker_stop() {
    print_status "🛑 Stopping all Docker services..."
    docker-compose down
    print_success "✅ Services stopped"
}

# Function to restart services
docker_restart() {
    print_status "🔄 Restarting all Docker services..."
    docker-compose restart db redis web celery celery-beat telegram-bot
    sleep 3
    print_success "✅ Services restarted"
}

# Function to restart individual service
docker_restart_service() {
    local service="$1"
    local service_name="$2"
    
    if [ -z "$service" ]; then
        print_error "Service name required"
        return 1
    fi
    
    print_status "🔄 Restarting $service_name..."
    
    # Check if service exists
    if ! docker-compose ps "$service" >/dev/null 2>&1; then
        print_error "Service '$service' not found"
        return 1
    fi
    
    # Restart the service
    if docker-compose restart "$service"; then
        sleep 2
        print_success "✅ $service_name restarted"
        
        # Show basic health check for web service
        if [ "$service" = "web" ]; then
            sleep 3
            if check_service_health "Web App" "http://localhost:8800/health/" 5; then
                print_success "✅ Web service is responding"
            else
                print_warning "⚠️ Web service may not be fully ready yet"
            fi
        fi
        return 0
    else
        print_error "❌ Failed to restart $service_name"
        return 1
    fi
}

# Function to rebuild and restart
docker_rebuild() {
    print_status "🏗️ Rebuilding and restarting all services..."
    check_env_file
    check_docker
    docker-compose build
    docker-compose up -d db redis
    wait_for_database || true
    docker-compose up -d web celery celery-beat --no-deps
    docker-compose up -d --scale telegram-bot=1 telegram-bot --no-deps
    sleep 3
    # Ensure DB is migrated and Playwright browsers are present
    docker_migrate || true
    docker_playwright_install || true
    print_success "✅ Services rebuilt and restarted"
}

# Function to rebuild individual service
docker_rebuild_service() {
    local service="$1"
    local service_name="$2"
    
    if [ -z "$service" ]; then
        print_error "Service name required"
        return 1
    fi
    
    print_status "🏗️ Rebuilding $service_name..."
    check_env_file
    check_docker
    
    # Build the service
    if docker-compose build "$service"; then
        print_status "🚀 Starting rebuilt $service_name..."
        
        # Handle special cases for service startup
        case "$service" in
            "db"|"redis")
                # Infrastructure services
                docker-compose up -d "$service"
                if [ "$service" = "db" ]; then
                    wait_for_database || true
                fi
                ;;
            "telegram-bot")
                # Ensure single instance
                docker-compose up -d --scale telegram-bot=1 "$service"
                ;;
            "web")
                # Web service needs infrastructure
                docker-compose up -d db redis
                wait_for_database || true
                docker-compose up -d "$service" --no-deps
                ;;
            "celery"|"celery-beat")
                # Workers need infrastructure
                docker-compose up -d db redis
                wait_for_database || true
                docker-compose up -d "$service" --no-deps
                ;;
            "flower")
                # Monitoring service
                docker-compose up -d "$service"
                ;;
            *)
                # Default case
                docker-compose up -d "$service"
                ;;
        esac
        
        sleep 3
        print_success "✅ $service_name rebuilt and restarted"
        
        # Special post-rebuild actions
        case "$service" in
            "web")
                # Run migrations and install Playwright for web service
                print_status "🔧 Running post-rebuild setup for web service..."
                docker_migrate || true
                docker_playwright_install || true
                
                # Health check
                sleep 3
                if check_service_health "Web App" "http://localhost:8800/health/" 5; then
                    print_success "✅ Web service is responding"
                else
                    print_warning "⚠️ Web service may not be fully ready yet"
                fi
                ;;
            "celery")
                # Install Playwright for celery worker
                print_status "🎭 Installing Playwright for Celery worker..."
                docker_playwright_install || true
                ;;
        esac
        
        return 0
    else
        print_error "❌ Failed to rebuild $service_name"
        return 1
    fi
}

# Function to run migrations
docker_migrate() {
    print_status "📊 Running database migrations..."
    docker-compose exec web python manage.py makemigrations
    docker-compose exec web python manage.py migrate
    print_success "✅ Migrations completed"
}

# Function to start Flower monitoring
docker_monitor() {
    print_status "🌸 Starting Flower monitoring..."
    docker-compose --profile monitoring up -d flower
    sleep 2
    if check_service_health "Flower" "http://localhost:5555" 5; then
        print_success "✅ Flower available at http://localhost:5555"
    else
        print_warning "⚠️ Flower started but may not be ready yet"
        print_status "💡 Try accessing http://localhost:5555 in a moment"
    fi
}

# Function to open Django shell
docker_shell() {
    print_status "🐚 Opening Django shell..."
    docker-compose exec web python manage.py shell
}

# Function to clean up Docker resources (enhanced)
docker_clean() {
    print_status "🧹 Cleaning up Docker resources..."
    print_warning "⚠️  This will remove all containers, volumes, and unused images"
    
    if [ "${1:-}" != "--force" ]; then
        read -p "Continue? (y/N): " -r
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            print_status "Cleanup cancelled"
            return 0
        fi
    fi
    
    docker-compose down -v 2>/dev/null || true
    docker system prune -f 2>/dev/null || true
    
    # Also clean up any dangling images
    docker image prune -f 2>/dev/null || true
    
    print_success "✅ Cleanup completed - ready for fresh setup"
}

# Function to show error logs only
docker_error_logs() {
    local service="$1"
    local service_name="$2"
    
    if [ -n "$service" ]; then
        print_status "🚨 Viewing error logs for $service_name (Press Ctrl+C to return to menu)"
        echo "=================================="
        echo
        # Filter for error patterns using grep
        docker-compose logs -f "$service" 2>&1 | grep -i --line-buffered -E "(error|critical|fatal|exception|traceback|warning|fail)"
    else
        print_status "🚨 Viewing error logs for all services (Press Ctrl+C to return to menu)"
        echo "=================================="
        echo
        # Filter for error patterns from all services
        docker-compose logs -f 2>&1 | grep -i --line-buffered -E "(error|critical|fatal|exception|traceback|warning|fail)"
    fi
}

# Function to show logs menu
logs_menu() {
    while true; do
        show_header
        print_status "📋 Docker Logs Viewer"
        echo "====================="
        echo
        
		local services=("web" "db" "redis" "celery" "celery-beat" "flower" "telegram-bot")
		local service_names=("Web App" "PostgreSQL" "Redis" "Celery Worker" "Celery Beat" "Flower Monitor" "Telegram Bot")
        local available_services=()
        local available_names=()
        local count=1
        
        # Check which services are running
        for i in "${!services[@]}"; do
            if docker-compose ps "${services[$i]}" 2>/dev/null | grep -q "Up"; then
                available_services+=("${services[$i]}")
                available_names+=("${service_names[$i]}")
                echo "  $count) ${service_names[$i]}"
                count=$((count + 1))
            fi
        done
        
        if [ ${#available_services[@]} -eq 0 ]; then
            print_warning "No services are currently running."
            echo
            echo "  b) ⬅️  Back to main menu"
            echo
            
            read -p "Select an option (b): " choice
            case "$choice" in
                "b"|"B")
                    return
                    ;;
                *)
                    print_error "Invalid choice."
                    sleep 2
                    ;;
            esac
            continue
        fi
        
        echo "  a) 📊 All services"
        echo "  e) 🚨 All services (errors only)"
        echo "  r) 🔄 Refresh"
        echo "  b) ⬅️  Back to main menu"
        echo
        
        read -p "Select logs to view (1-${#available_services[@]}, a, e, r, b): " choice
        
        case "$choice" in
            [1-9]*)
                if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le ${#available_services[@]} ]; then
                    local selected_service="${available_services[$((choice-1))]}"
                    local selected_name="${available_names[$((choice-1))]}"
                    show_header
                    print_status "📋 Log options for $selected_name"
                    echo "=================================="
                    echo "  1) 📊 All logs"
                    echo "  2) 🚨 Errors only"
                    echo "  b) ⬅️  Back to service menu"
                    echo
                    read -p "Select log type (1, 2, b): " log_choice
                    case "$log_choice" in
                        "1")
                            show_header
                            print_status "📋 Viewing all logs for $selected_name (Press Ctrl+C to return to menu)"
                            echo "=================================="
                            echo
                            docker-compose logs -f "$selected_service"
                            ;;
                        "2")
                            show_header
                            docker_error_logs "$selected_service" "$selected_name"
                            ;;
                        "b"|"B")
                            # Return to service menu
                            ;;
                        *)
                            print_error "Invalid choice."
                            sleep 2
                            ;;
                    esac
                else
                    print_error "Invalid choice. Please select a number between 1 and ${#available_services[@]}."
                    sleep 2
                fi
                ;;
            "a"|"A")
                show_header
                print_status "📋 Viewing all service logs (Press Ctrl+C to return to menu)"
                echo "=================================="
                echo
                docker-compose logs -f
                ;;
            "e"|"E")
                show_header
                docker_error_logs
                ;;
            "r"|"R")
                # Refresh - just continue the loop
                ;;
            "b"|"B")
                return
                ;;
            *)
                print_error "Invalid choice. Please try again."
                sleep 2
                ;;
        esac
    done
}

# Function to show restart individual services menu
restart_individual_menu() {
    while true; do
        show_header
        print_status "🔄 Restart Individual Services"
        echo "=============================="
        echo
        
        local services=("web" "db" "redis" "celery" "celery-beat" "flower" "telegram-bot")
        local service_names=("Web App" "PostgreSQL" "Redis" "Celery Worker" "Celery Beat" "Flower Monitor" "Telegram Bot")
        local available_services=()
        local available_names=()
        local count=1
        
        # Check which services are running
        for i in "${!services[@]}"; do
            if docker-compose ps "${services[$i]}" 2>/dev/null | grep -q "Up"; then
                available_services+=("${services[$i]}")
                available_names+=("${service_names[$i]}")
                echo "  $count) ${service_names[$i]} (Running)"
                count=$((count + 1))
            else
                # Show stopped services too, as we might want to restart them
                available_services+=("${services[$i]}")
                available_names+=("${service_names[$i]}")
                echo "  $count) ${service_names[$i]} (Stopped)"
                count=$((count + 1))
            fi
        done
        
        echo
        echo "  a) 🔄 Restart all services"
        echo "  m) 📦 Multi-select services"
        echo "  r) 🔄 Refresh"
        echo "  b) ⬅️  Back to main menu"
        echo
        
        read -p "Select service to restart (1-${#available_services[@]}, a, m, r, b): " choice
        
        case "$choice" in
            [1-9]*)
                if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le ${#available_services[@]} ]; then
                    local selected_service="${available_services[$((choice-1))]}"
                    local selected_name="${available_names[$((choice-1))]}"
                    show_header
                    docker_restart_service "$selected_service" "$selected_name"
                    pause
                else
                    print_error "Invalid choice. Please select a number between 1 and ${#available_services[@]}."
                    sleep 2
                fi
                ;;
            "a"|"A")
                show_header
                docker_restart
                pause
                ;;
            "m"|"M")
                # Multi-select menu
                multiselect_restart_menu "${available_services[@]}" "${available_names[@]}"
                ;;
            "r"|"R")
                # Refresh - just continue the loop
                ;;
            "b"|"B")
                return
                ;;
            *)
                print_error "Invalid choice. Please try again."
                sleep 2
                ;;
        esac
    done
}

# Function to show rebuild individual services menu
rebuild_individual_menu() {
    while true; do
        show_header
        print_status "🏗️ Rebuild Individual Services"
        echo "==============================="
        echo
        
        local services=("web" "db" "redis" "celery" "celery-beat" "flower" "telegram-bot")
        local service_names=("Web App" "PostgreSQL" "Redis" "Celery Worker" "Celery Beat" "Flower Monitor" "Telegram Bot")
        local count=1
        
        # Show all services (whether running or not)
        for i in "${!services[@]}"; do
            if docker-compose ps "${services[$i]}" 2>/dev/null | grep -q "Up"; then
                echo "  $count) ${service_names[$i]} (Running)"
            else
                echo "  $count) ${service_names[$i]} (Stopped)"
            fi
            count=$((count + 1))
        done
        
        echo
        echo "  a) 🏗️ Rebuild all services"
        echo "  m) 📦 Multi-select services"
        echo "  r) 🔄 Refresh"
        echo "  b) ⬅️  Back to main menu"
        echo
        
        read -p "Select service to rebuild (1-${#services[@]}, a, m, r, b): " choice
        
        case "$choice" in
            [1-9]*)
                if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le ${#services[@]} ]; then
                    local selected_service="${services[$((choice-1))]}"
                    local selected_name="${service_names[$((choice-1))]}"
                    show_header
                    docker_rebuild_service "$selected_service" "$selected_name"
                    pause
                else
                    print_error "Invalid choice. Please select a number between 1 and ${#services[@]}."
                    sleep 2
                fi
                ;;
            "a"|"A")
                show_header
                docker_rebuild
                pause
                ;;
            "m"|"M")
                # Multi-select menu
                multiselect_rebuild_menu "${services[@]}" "${service_names[@]}"
                ;;
            "r"|"R")
                # Refresh - just continue the loop
                ;;
            "b"|"B")
                return
                ;;
            *)
                print_error "Invalid choice. Please try again."
                sleep 2
                ;;
        esac
    done
}

# Function for multi-select restart menu
multiselect_restart_menu() {
    # Accept arrays directly as arguments (bash 3.x compatible)
    local services_array=()
    local names_array=()
    local selected_services=()
    local selected_names=()
    
    # Parse arguments: first half are services, second half are names
    local total_args=$#
    local half=$((total_args / 2))
    
    # Fill services array
    local i=1
    while [ $i -le $half ]; do
        services_array+=("${!i}")
        i=$((i + 1))
    done
    
    # Fill names array
    i=$((half + 1))
    while [ $i -le $total_args ]; do
        names_array+=("${!i}")
        i=$((i + 1))
    done
    
    while true; do
        show_header
        print_status "🔄 Multi-Select Services to Restart"
        echo "===================================="
        echo
        echo "Selected services:"
        if [ ${#selected_services[@]} -eq 0 ]; then
            echo "  (none selected)"
        else
            for name in "${selected_names[@]}"; do
                echo "  ✓ $name"
            done
        fi
        echo
        echo "Available services:"
        
        for i in "${!services_array[@]}"; do
            local service="${services_array[$i]}"
            local name="${names_array[$i]}"
            local is_selected=false
            
            # Check if service is already selected
            for selected in "${selected_services[@]}"; do
                if [ "$selected" = "$service" ]; then
                    is_selected=true
                    break
                fi
            done
            
            if [ "$is_selected" = true ]; then
                echo "  $((i+1))) ✓ $name"
            else
                echo "  $((i+1))) ○ $name"
            fi
        done
        
        echo
        echo "  a) 🚀 Restart selected services"
        echo "  c) 🧹 Clear selection"
        echo "  b) ⬅️  Back"
        echo
        
        read -p "Toggle service (1-${#services_array[@]}) or action (a, c, b): " choice
        
        case "$choice" in
            [1-9]*)
                if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le ${#services_array[@]} ]; then
                    local idx=$((choice-1))
                    local service="${services_array[$idx]}"
                    local name="${names_array[$idx]}"
                    local is_selected=false
                    local selected_idx=-1
                    
                    # Check if already selected
                    for i in "${!selected_services[@]}"; do
                        if [ "${selected_services[$i]}" = "$service" ]; then
                            is_selected=true
                            selected_idx=$i
                            break
                        fi
                    done
                    
                    if [ "$is_selected" = true ]; then
                        # Remove from selection
                        unset selected_services[$selected_idx]
                        unset selected_names[$selected_idx]
                        selected_services=("${selected_services[@]}")
                        selected_names=("${selected_names[@]}")
                    else
                        # Add to selection
                        selected_services+=("$service")
                        selected_names+=("$name")
                    fi
                else
                    print_error "Invalid choice. Please select a number between 1 and ${#services_array[@]}."
                    sleep 2
                fi
                ;;
            "a"|"A")
                if [ ${#selected_services[@]} -eq 0 ]; then
                    print_error "No services selected."
                    sleep 2
                else
                    show_header
                    print_status "🔄 Restarting selected services..."
                    local failed_services=()
                    
                    for i in "${!selected_services[@]}"; do
                        local service="${selected_services[$i]}"
                        local name="${selected_names[$i]}"
                        if ! docker_restart_service "$service" "$name"; then
                            failed_services+=("$name")
                        fi
                    done
                    
                    if [ ${#failed_services[@]} -eq 0 ]; then
                        print_success "✅ All selected services restarted successfully!"
                    else
                        print_warning "⚠️ Some services failed to restart: ${failed_services[*]}"
                    fi
                    pause
                    return
                fi
                ;;
            "c"|"C")
                selected_services=()
                selected_names=()
                ;;
            "b"|"B")
                return
                ;;
            *)
                print_error "Invalid choice. Please try again."
                sleep 2
                ;;
        esac
    done
}

# Function for multi-select rebuild menu
multiselect_rebuild_menu() {
    # Accept arrays directly as arguments (bash 3.x compatible)
    local services_array=()
    local names_array=()
    local selected_services=()
    local selected_names=()
    
    # Parse arguments: first half are services, second half are names
    local total_args=$#
    local half=$((total_args / 2))
    
    # Fill services array
    local i=1
    while [ $i -le $half ]; do
        services_array+=("${!i}")
        i=$((i + 1))
    done
    
    # Fill names array
    i=$((half + 1))
    while [ $i -le $total_args ]; do
        names_array+=("${!i}")
        i=$((i + 1))
    done
    
    while true; do
        show_header
        print_status "🏗️ Multi-Select Services to Rebuild"
        echo "===================================="
        echo
        echo "Selected services:"
        if [ ${#selected_services[@]} -eq 0 ]; then
            echo "  (none selected)"
        else
            for name in "${selected_names[@]}"; do
                echo "  ✓ $name"
            done
        fi
        echo
        echo "Available services:"
        
        for i in "${!services_array[@]}"; do
            local service="${services_array[$i]}"
            local name="${names_array[$i]}"
            local is_selected=false
            
            # Check if service is already selected
            for selected in "${selected_services[@]}"; do
                if [ "$selected" = "$service" ]; then
                    is_selected=true
                    break
                fi
            done
            
            if [ "$is_selected" = true ]; then
                echo "  $((i+1))) ✓ $name"
            else
                echo "  $((i+1))) ○ $name"
            fi
        done
        
        echo
        echo "  a) 🚀 Rebuild selected services"
        echo "  c) 🧹 Clear selection"
        echo "  b) ⬅️  Back"
        echo
        
        read -p "Toggle service (1-${#services_array[@]}) or action (a, c, b): " choice
        
        case "$choice" in
            [1-9]*)
                if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le ${#services_array[@]} ]; then
                    local idx=$((choice-1))
                    local service="${services_array[$idx]}"
                    local name="${names_array[$idx]}"
                    local is_selected=false
                    local selected_idx=-1
                    
                    # Check if already selected
                    for i in "${!selected_services[@]}"; do
                        if [ "${selected_services[$i]}" = "$service" ]; then
                            is_selected=true
                            selected_idx=$i
                            break
                        fi
                    done
                    
                    if [ "$is_selected" = true ]; then
                        # Remove from selection
                        unset selected_services[$selected_idx]
                        unset selected_names[$selected_idx]
                        selected_services=("${selected_services[@]}")
                        selected_names=("${selected_names[@]}")
                    else
                        # Add to selection
                        selected_services+=("$service")
                        selected_names+=("$name")
                    fi
                else
                    print_error "Invalid choice. Please select a number between 1 and ${#services_array[@]}."
                    sleep 2
                fi
                ;;
            "a"|"A")
                if [ ${#selected_services[@]} -eq 0 ]; then
                    print_error "No services selected."
                    sleep 2
                else
                    show_header
                    print_status "🏗️ Rebuilding selected services..."
                    local failed_services=()
                    
                    for i in "${!selected_services[@]}"; do
                        local service="${selected_services[$i]}"
                        local name="${selected_names[$i]}"
                        if ! docker_rebuild_service "$service" "$name"; then
                            failed_services+=("$name")
                        fi
                    done
                    
                    if [ ${#failed_services[@]} -eq 0 ]; then
                        print_success "✅ All selected services rebuilt successfully!"
                    else
                        print_warning "⚠️ Some services failed to rebuild: ${failed_services[*]}"
                    fi
                    pause
                    return
                fi
                ;;
            "c"|"C")
                selected_services=()
                selected_names=()
                ;;
            "b"|"B")
                return
                ;;
            *)
                print_error "Invalid choice. Please try again."
                sleep 2
                ;;
        esac
    done
}

# Telegram bot helpers
docker_bot_start() {
	print_status "🤖 Starting Telegram bot service..."
	check_env_file
	check_docker
	docker-compose up -d telegram-bot
	print_success "✅ Telegram bot started"
}

docker_bot_stop() {
	print_status "🛑 Stopping Telegram bot service..."
	docker-compose stop telegram-bot || true
	print_success "✅ Telegram bot stopped"
}

docker_bot_restart() {
	print_status "🔄 Restarting Telegram bot service..."
	docker-compose restart telegram-bot
	print_success "✅ Telegram bot restarted"
}

docker_bot_rebuild() {
	print_status "🏗️ Rebuilding Telegram bot image and restarting..."
	check_env_file
	check_docker
	docker-compose build telegram-bot
	docker-compose up -d telegram-bot
	print_success "✅ Telegram bot rebuilt and running"
}

docker_bot_logs() {
	print_status "📋 Showing Telegram bot logs (Ctrl+C to exit)..."
	docker-compose logs -f telegram-bot
}

# Function to clear screen and show header
show_header() {
    clear
    echo -e "${BLUE}🐳 News Trader Docker Manager${NC}"
    echo -e "${BLUE}=========================================${NC}"
    echo
}

# Function to pause and wait for user input
pause() {
    echo
    read -p "Press Enter to continue..." -r
    echo
}

# Function to show help
show_help() {
    echo "News Trader Docker Development Manager"
    echo "====================================="
    echo
    echo "Usage: $0 [command]"
    echo
    echo "Interactive Mode (default):"
    echo "  $0                    Launch interactive menu"
    echo
    echo "Command Line Mode:"
    echo "  setup     Robust setup with error recovery (can retry)"
    echo "  start     Start all services"
    echo "  stop      Stop all services"
    echo "  restart   Restart all services"
    echo "  restart-menu   Interactive menu to restart individual services"
    echo "  build     Rebuild all images"
    echo "  rebuild   Build and restart all services"
    echo "  rebuild-menu   Interactive menu to rebuild individual services"
    echo "  migrate   Run database migrations"
    echo "  monitor   Start Flower monitoring"
	echo "  bot-start Start Telegram bot service"
	echo "  bot-stop  Stop Telegram bot service"
	echo "  bot-restart Restart Telegram bot service"
	echo "  bot-rebuild Rebuild and start Telegram bot service"
	echo "  bot-logs  Tail Telegram bot logs"
    echo "  pwinstall Install Playwright Chromium in containers"
    echo "  shell     Open Django shell"
    echo "  logs      Show all logs"
    echo "  error-logs Show error logs only (filtered)"
    echo "  status    Show service status"
    echo "  clean     Clean up Docker resources (reset for retry)"
    echo "  help      Show this help"
    echo
    echo "Examples:"
    echo "  $0                    # Interactive mode"
    echo "  $0 setup              # Robust setup (can retry if failed)"
    echo "  $0 clean              # Reset after failed setup"
    echo "  $0 start              # Start services"
    echo "  $0 restart-menu       # Interactive menu to restart individual services"
    echo "  $0 rebuild-menu       # Interactive menu to rebuild individual services"
    echo "  $0 logs               # View all logs"
    echo "  $0 error-logs         # View error logs only"
    echo ""
    echo "Recovery from Failed Setup:"
    echo "  $0 clean && $0 setup  # Clean everything and retry setup"
    echo
    echo "Docker Environment:"
    echo "  - All services run in isolated containers"
    echo "  - Uses your existing .env file"
    echo "  - PostgreSQL database with persistent data"
    echo "  - Redis for Celery task queue"
    echo "  - Playwright (Chromium) for headless scraping"
}

# Function to show interactive menu
interactive_menu() {
    while true; do
        show_header
        
        # Show current Docker status
        show_docker_status
        echo
        
        echo -e "${YELLOW}📋 Available Actions:${NC}"
        echo "========================"
        echo "  1) 🚀 Setup (robust, can retry)"
        echo "  2) ▶️  Start all services"
        echo "  3) ⏹️  Stop all services" 
        echo "  4) 🔄 Restart all services"
        echo "  5) 🔄 Restart individual services"
        echo "  6) 🏗️  Rebuild images"
        echo "  7) 🔧 Rebuild & restart"
        echo "  8) 🏗️  Rebuild individual services"
        echo "  9) 📊 Run migrations"
        echo " 10) 🌸 Start Flower monitor"
        echo " 11) 🐚 Django shell"
        echo " 12) 📋 View logs"
        echo " 13) 🔍 Refresh status"
        echo " 14) 🧹 Clean up Docker (reset)"
        echo " 15) ❓ Show help"
        echo "  q) 🚪 Quit"
        echo
        
        read -p "Select an option (1-15, q): " choice
        echo
        
        case "$choice" in
            1)
                docker_setup
                pause
                ;;
            2)
                docker_start
                pause
                ;;
            3)
                docker_stop
                pause
                ;;
            4)
                docker_restart
                pause
                ;;
            5)
                restart_individual_menu
                ;;
            6)
                print_status "🏗️ Building Docker images..."
                check_env_file && check_docker && docker-compose build
                print_success "✅ Images rebuilt"
                pause
                ;;
            7)
                docker_rebuild
                pause
                ;;
            8)
                rebuild_individual_menu
                ;;
            9)
                docker_migrate
                pause
                ;;
            10)
                docker_monitor
                pause
                ;;
            11)
                docker_shell
                pause
                ;;
            12)
                logs_menu
                ;;
            13)
                # Just refresh - the loop will show status again
                ;;
            14)
                docker_clean
                pause
                ;;
            15)
                show_help
                pause
                ;;
            "q"|"Q")
                echo -e "${GREEN}👋 Goodbye!${NC}"
                exit 0
                ;;
            *)
                print_error "Invalid choice. Please try again."
                sleep 2
                ;;
        esac
    done
}

# Main script logic
if [ $# -eq 0 ]; then
    # No arguments provided - start interactive mode
    interactive_menu
else
    # Arguments provided - use command line mode
    case "$1" in
        "setup")
            docker_setup
            ;;
        "start")
            docker_start
            ;;
        "stop")
            docker_stop
            ;;
        "restart")
            docker_restart
            ;;
        "restart-menu")
            restart_individual_menu
            ;;
        "build")
            check_env_file && check_docker && docker-compose build
            print_success "✅ Images rebuilt"
            ;;
        "rebuild")
            docker_rebuild
            ;;
        "rebuild-menu")
            rebuild_individual_menu
            ;;
        "migrate")
            docker_migrate
            ;;
        "monitor")
            docker_monitor
            ;;
        "pwinstall")
            docker_playwright_install
            ;;
        "shell")
            docker_shell
            ;;
        "logs")
            docker-compose logs -f
            ;;
        "error-logs")
            docker_error_logs
            ;;
        "bot-start")
            docker_bot_start
            ;;
        "bot-stop")
            docker_bot_stop
            ;;
        "bot-restart")
            docker_bot_restart
            ;;
        "bot-rebuild")
            docker_bot_rebuild
            ;;
        "bot-logs")
            docker_bot_logs
            ;;
        "status")
            show_docker_status
            ;;
        "clean")
            docker_clean --force
            ;;
        "cleanup")
            docker_clean --force
            ;;
        "reset")
            docker_clean --force
            ;;
        "help"|"-h"|"--help")
            show_help
            ;;
        "interactive"|"menu")
            interactive_menu
            ;;
        *)
            print_error "Unknown command: $1"
            echo
            print_status "💡 Tip: If setup failed, try:"
            print_status "   $0 clean && $0 setup"
            echo
            show_help
            exit 1
            ;;
    esac
fi 