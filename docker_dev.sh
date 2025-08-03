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
    local services=("web" "db" "redis" "celery" "celery-beat")
    local service_names=("Web App" "PostgreSQL" "Redis" "Celery Worker" "Celery Beat")
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
    if check_service_health "Web App" "http://localhost:8000/health/" 3; then
        echo -e "  ${GREEN}✓${NC} Web App (http://localhost:8000)"
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
        echo -e "  ${BLUE}🌐 Web App: http://localhost:8000${NC}"
        echo -e "  ${BLUE}⚙️  Admin: http://localhost:8000/admin/${NC}"
        echo -e "  ${BLUE}🌸 Flower: http://localhost:5555${NC} (if started)"
    elif [ $running_count -gt 0 ]; then
        echo -e "  ${YELLOW}⚠️  $running_count of ${#services[@]} core services running${NC}"
    else
        echo -e "  ${RED}❌ No services running${NC}"
        echo -e "  ${YELLOW}💡 Use 'setup' for first time or 'start' to begin${NC}"
    fi
}

# Function to setup (first time)
docker_setup() {
    print_status "🚀 First time Docker setup..."
    check_env_file
    check_docker
    
    print_status "🏗️ Building Docker images..."
    docker-compose build
    
    print_status "🗄️ Starting database and Redis..."
    docker-compose up -d db redis
    
    print_status "⏳ Waiting for database to be ready..."
    sleep 10
    
    print_status "📊 Running database migrations..."
    docker-compose run --rm web python manage.py migrate
    
    print_status "📁 Collecting static files..."
    docker-compose run --rm web python manage.py collectstatic --noinput
    
    print_status "🚀 Starting all services..."
    docker-compose up -d
    
    sleep 5
    print_success "✅ Setup completed!"
    echo ""
    print_success "🌐 Web App: http://localhost:8000"
    print_success "🌸 Flower Monitor: http://localhost:5555 (use monitor option)"
    echo ""
    print_status "💡 Your News Trader is ready for testing!"
}

# Function to start services
docker_start() {
    print_status "🚀 Starting all Docker services..."
    check_env_file
    check_docker
    docker-compose up -d
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
    docker-compose restart
    sleep 3
    print_success "✅ Services restarted"
}

# Function to rebuild and restart
docker_rebuild() {
    print_status "🏗️ Rebuilding and restarting all services..."
    check_env_file
    check_docker
    docker-compose build
    docker-compose up -d
    sleep 3
    print_success "✅ Services rebuilt and restarted"
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

# Function to clean up Docker resources
docker_clean() {
    print_status "🧹 Cleaning up Docker resources..."
    docker-compose down -v
    docker system prune -f
    print_success "✅ Cleanup completed"
}

# Function to show logs menu
logs_menu() {
    while true; do
        show_header
        print_status "📋 Docker Logs Viewer"
        echo "====================="
        echo
        
        local services=("web" "db" "redis" "celery" "celery-beat" "flower")
        local service_names=("Web App" "PostgreSQL" "Redis" "Celery Worker" "Celery Beat" "Flower Monitor")
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
        echo "  r) 🔄 Refresh"
        echo "  b) ⬅️  Back to main menu"
        echo
        
        read -p "Select logs to view (1-${#available_services[@]}, a, r, b): " choice
        
        case "$choice" in
            [1-9]*)
                if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le ${#available_services[@]} ]; then
                    local selected_service="${available_services[$((choice-1))]}"
                    local selected_name="${available_names[$((choice-1))]}"
                    show_header
                    print_status "📋 Viewing logs for $selected_name (Press Ctrl+C to return to menu)"
                    echo "=================================="
                    echo
                    docker-compose logs -f "$selected_service"
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
    echo "  setup     First time setup (build, migrate, start)"
    echo "  start     Start all services"
    echo "  stop      Stop all services"
    echo "  restart   Restart all services"
    echo "  build     Rebuild all images"
    echo "  rebuild   Build and restart all services"
    echo "  migrate   Run database migrations"
    echo "  monitor   Start Flower monitoring"
    echo "  shell     Open Django shell"
    echo "  logs      Show all logs"
    echo "  status    Show service status"
    echo "  clean     Clean up Docker resources"
    echo "  help      Show this help"
    echo
    echo "Examples:"
    echo "  $0                    # Interactive mode"
    echo "  $0 setup              # First time setup"
    echo "  $0 start              # Start services"
    echo "  $0 logs               # View all logs"
    echo
    echo "Docker Environment:"
    echo "  - All services run in isolated containers"
    echo "  - Uses your existing .env file"
    echo "  - PostgreSQL database with persistent data"
    echo "  - Redis for Celery task queue"
    echo "  - Selenium with Chrome for web scraping"
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
        echo "  1) 🚀 Setup (first time)"
        echo "  2) ▶️  Start all services"
        echo "  3) ⏹️  Stop all services" 
        echo "  4) 🔄 Restart all services"
        echo "  5) 🏗️  Rebuild images"
        echo "  6) 🔧 Rebuild & restart"
        echo "  7) 📊 Run migrations"
        echo "  8) 🌸 Start Flower monitor"
        echo "  9) 🐚 Django shell"
        echo " 10) 📋 View logs"
        echo " 11) 🔍 Refresh status"
        echo " 12) 🧹 Clean up Docker"
        echo " 13) ❓ Show help"
        echo "  q) 🚪 Quit"
        echo
        
        read -p "Select an option (1-13, q): " choice
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
                print_status "🏗️ Building Docker images..."
                check_env_file && check_docker && docker-compose build
                print_success "✅ Images rebuilt"
                pause
                ;;
            6)
                docker_rebuild
                pause
                ;;
            7)
                docker_migrate
                pause
                ;;
            8)
                docker_monitor
                pause
                ;;
            9)
                docker_shell
                pause
                ;;
            10)
                logs_menu
                ;;
            11)
                # Just refresh - the loop will show status again
                ;;
            12)
                docker_clean
                pause
                ;;
            13)
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
        "build")
            check_env_file && check_docker && docker-compose build
            print_success "✅ Images rebuilt"
            ;;
        "rebuild")
            docker_rebuild
            ;;
        "migrate")
            docker_migrate
            ;;
        "monitor")
            docker_monitor
            ;;
        "shell")
            docker_shell
            ;;
        "logs")
            docker-compose logs -f
            ;;
        "status")
            show_docker_status
            ;;
        "clean")
            docker_clean
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
            show_help
            exit 1
            ;;
    esac
fi 