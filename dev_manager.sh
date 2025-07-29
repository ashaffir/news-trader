#!/bin/bash

# News Trader Local Development Manager
# Interactive management for local development environment without Docker

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Project configuration
PROJECT_NAME="news-trader"
VENV_NAME="venv"
ENV_FILE=".env"
LOCAL_SETTINGS_FILE="news_trader/local_settings.py"
LOGS_DIR="logs"
PID_DIR="pids"

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

print_process() {
    echo -e "${PURPLE}[PROCESS]${NC} $1"
}

print_menu() {
    echo -e "${CYAN}[MENU]${NC} $1"
}

# Function to pause for user interaction
pause_for_user() {
    echo
    read -p "Press Enter to continue..." -r
    echo
}

# Function to clear screen
clear_screen() {
    clear
    echo -e "${CYAN}🚀 News Trader Development Manager${NC}"
    echo -e "${CYAN}======================================${NC}"
    echo
}

# Function to create directories
create_directories() {
    mkdir -p "$LOGS_DIR" "$PID_DIR"
}

# Function to check if command exists
command_exists() {
    # Ensure PATH includes common locations
    export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:$PATH"
    
    # First try standard command detection
    if command -v "$1" >/dev/null 2>&1; then
        return 0
    fi
    
    # For node specifically, check common paths directly
    if [ "$1" = "node" ]; then
        if [ -f "/opt/homebrew/bin/node" ] || [ -f "/usr/local/bin/node" ] || [ -f "/usr/bin/node" ]; then
            return 0
        fi
    fi
    
    return 1
}

# Function to test URL connectivity
test_url() {
    local url="$1"
    local timeout="${2:-5}"
    curl -s --max-time "$timeout" "$url" >/dev/null 2>&1
}

# Function to test WebSocket connectivity
test_websocket() {
    local ws_test_script="/tmp/ws_test_$$.js"
    cat > "$ws_test_script" << 'EOF'
const WebSocket = require('ws');
const ws = new WebSocket('ws://localhost:8000/ws/dashboard/');
let connected = false;

ws.on('open', function open() {
    connected = true;
    console.log('websocket_ok');
    ws.close();
    process.exit(0);
});

ws.on('error', function error(err) {
    console.log('websocket_error');
    process.exit(1);
});

setTimeout(() => {
    if (!connected) {
        console.log('websocket_timeout');
        process.exit(1);
    }
}, 3000);
EOF
    
    # Try different node paths and check if node is available
    local node_path=""
    if command -v node >/dev/null 2>&1; then
        node_path="node"
    elif [ -f "/opt/homebrew/bin/node" ]; then
        node_path="/opt/homebrew/bin/node"
    elif [ -f "/usr/local/bin/node" ]; then
        node_path="/usr/local/bin/node"
    fi
    
    if [ -n "$node_path" ]; then
        local result=$($node_path "$ws_test_script" 2>/dev/null)
        rm -f "$ws_test_script"
        echo "$result"
    else
        rm -f "$ws_test_script"
        echo "node_not_available"
    fi
}

# Function to get service health
get_service_health() {
    local service="$1"
    case "$service" in
        "django")
            if test_url "http://localhost:8000/dashboard/" 3; then
                echo "healthy"
            elif test_url "http://localhost:8000/" 3; then
                echo "responding"
            else
                echo "unhealthy"
            fi
            ;;
        "websocket")
            # Test WebSocket connection from project directory where ws module is available
            if cd "$(pwd)" && /opt/homebrew/bin/node -e "
const WebSocket = require('ws');
const ws = new WebSocket('ws://localhost:8000/ws/dashboard/');
ws.on('open', () => { ws.close(); process.exit(0); });
ws.on('error', () => process.exit(1));
setTimeout(() => process.exit(1), 3000);
" >/dev/null 2>&1; then
                echo "healthy"
            else
                echo "unhealthy"
            fi
            ;;
        "admin")
            if test_url "http://localhost:8000/admin/" 3; then
                echo "healthy"
            else
                echo "unhealthy"
            fi
            ;;
        *)
            echo "unknown"
            ;;
    esac
}

# Function to explain errors with helpful tooltips
explain_error() {
    local error_type="$1"
    local context="${2:-}"
    
    case "$error_type" in
        "dependency_missing")
            cat << EOF
${YELLOW}💡 Error Explanation:${NC}
${RED}Missing Dependency: $context${NC}

${BLUE}What this means:${NC}
• A required system package is not installed on your machine
• This prevents the development environment from running properly

${GREEN}How to fix:${NC}
• macOS (Homebrew): brew install $context
• Ubuntu/Debian: sudo apt-get install $context
• CentOS/RHEL: sudo yum install $context

${PURPLE}Why this happened:${NC}
• Fresh system setup or missing package installation
• Package was uninstalled or corrupted
EOF
            ;;
        "postgresql_not_running")
            cat << EOF
${YELLOW}💡 Error Explanation:${NC}
${RED}PostgreSQL Database Not Running${NC}

${BLUE}What this means:${NC}
• PostgreSQL database server is not started on your system
• The application needs PostgreSQL to store data

${GREEN}How to fix:${NC}
• macOS (Homebrew): brew services start postgresql
• Ubuntu/Debian: sudo systemctl start postgresql
• Manual: pg_ctl -D /usr/local/var/postgres start

${PURPLE}Why this happened:${NC}
• System restart (PostgreSQL doesn't auto-start)
• PostgreSQL service was manually stopped
• Installation issue or configuration problem

${CYAN}Alternative:${NC}
• Install and start PostgreSQL if not installed:
  brew install postgresql (macOS)
  sudo apt-get install postgresql (Ubuntu)
EOF
            ;;
        "redis_not_running")
            cat << EOF
${YELLOW}💡 Error Explanation:${NC}
${RED}Redis Server Not Running${NC}

${BLUE}What this means:${NC}
• Redis server is not started (needed for WebSocket & Celery)
• Real-time features and background tasks won't work

${GREEN}How to fix:${NC}
• macOS (Homebrew): brew services start redis
• Ubuntu/Debian: sudo systemctl start redis
• Manual: redis-server

${PURPLE}Why this happened:${NC}
• System restart (Redis doesn't auto-start)
• Redis service was manually stopped
• Installation issue

${CYAN}Alternative:${NC}
• Install Redis if not installed:
  brew install redis (macOS)
  sudo apt-get install redis-server (Ubuntu)
EOF
            ;;
        "port_conflict")
            cat << EOF
${YELLOW}💡 Error Explanation:${NC}
${RED}Port Conflict: Port $context is already in use${NC}

${BLUE}What this means:${NC}
• Another process is using the port needed by our application
• This prevents the service from starting properly

${GREEN}How to fix:${NC}
• Automatic: Use the script's port conflict resolution (recommended)
• Manual: Find and kill the process using: lsof -i :$context
• Alternative: Use a different port in configuration

${PURPLE}Why this happened:${NC}
• Previous instance of application is still running
• Another application is using the same port
• System didn't clean up properly after last shutdown

${CYAN}Common causes:${NC}
• Docker containers still running in background
• Previous Django development server not properly stopped
• Another web server (nginx, apache) using port 8000
EOF
            ;;
        "websocket_failed")
            cat << EOF
${YELLOW}💡 Error Explanation:${NC}
${RED}WebSocket Connection Failed${NC}

${BLUE}What this means:${NC}
• Real-time communication between browser and server is broken
• Dashboard updates and live features won't work properly

${GREEN}How to fix:${NC}
• Ensure Redis is running: redis-cli ping
• Restart Django server with WebSocket support
• Check local_settings.py has correct CHANNEL_LAYERS configuration
• Verify no firewall blocking WebSocket connections

${PURPLE}Why this happened:${NC}
• Redis not available for WebSocket channels
• Django not running with ASGI (WebSocket support)
• Configuration mismatch between Docker and local settings
• Browser security blocking WebSocket connections

${CYAN}Debugging:${NC}
• Check browser console for WebSocket errors
• Verify URL: ws://localhost:8000/ws/dashboard/
• Test Redis: redis-cli ping should return PONG
EOF
            ;;
        "django_unhealthy")
            cat << EOF
${YELLOW}💡 Error Explanation:${NC}
${RED}Django Server Not Responding Properly${NC}

${BLUE}What this means:${NC}
• Django process is running but not serving requests correctly
• Web pages may be loading slowly or showing errors

${GREEN}How to fix:${NC}
• Check Django logs: ./dev_manager.sh logs django
• Restart Django: ./dev_manager.sh restart
• Verify database connection: ./dev_manager.sh check-ports
• Check for migration issues: ./dev_manager.sh cmd migrate

${PURPLE}Why this happened:${NC}
• Database connectivity issues
• Python dependencies missing or incompatible
• Configuration errors in settings
• High server load or resource constraints

${CYAN}Common solutions:${NC}
• Database not ready when Django started
• Virtual environment not properly activated
• Static files not collected: ./dev_manager.sh cmd collectstatic
EOF
            ;;
        "virtual_env_missing")
            cat << EOF
${YELLOW}💡 Error Explanation:${NC}
${RED}Python Virtual Environment Missing${NC}

${BLUE}What this means:${NC}
• Python dependencies are not isolated in a virtual environment
• This can cause version conflicts and missing packages

${GREEN}How to fix:${NC}
• Run: ./dev_manager.sh venv
• Or manually: python3 -m venv venv && source venv/bin/activate
• Then install dependencies: pip install -r requirements.txt

${PURPLE}Why this happened:${NC}
• First time setup not completed
• Virtual environment was deleted or corrupted
• Working in wrong directory

${CYAN}Why virtual environments matter:${NC}
• Isolates project dependencies from system Python
• Prevents version conflicts between projects
• Makes deployment more predictable
EOF
            ;;
        "database_connection_failed")
            cat << EOF
${YELLOW}💡 Error Explanation:${NC}
${RED}Database Connection Failed${NC}

${BLUE}What this means:${NC}
• Django cannot connect to the PostgreSQL database
• Data operations will fail

${GREEN}How to fix:${NC}
• Ensure PostgreSQL is running: pg_isready -h localhost
• Check database exists: ./dev_manager.sh db-setup
• Verify credentials in local_settings.py
• Reset database if corrupted: ./dev_manager.sh db-reset

${PURPLE}Why this happened:${NC}
• PostgreSQL service not running
• Database 'news_trader' doesn't exist
• Authentication failure (wrong password)
• Network connectivity issues

${CYAN}Quick diagnosis:${NC}
• Test connection: psql -h localhost -U news_trader -d news_trader
• Check process: ps aux | grep postgres
• Review logs: tail -f logs/django.log
EOF
            ;;
        *)
            cat << EOF
${YELLOW}💡 Error Explanation:${NC}
${RED}Unknown Error: $error_type${NC}

${BLUE}What to do:${NC}
• Check the logs: ./dev_manager.sh logs
• Review recent changes to configuration
• Try restarting services: ./dev_manager.sh restart
• Check system resources: top or htop

${GREEN}Getting help:${NC}
• Copy exact error message
• Include relevant log output
• Note what you were trying to do when error occurred
• Check if issue persists after restart
EOF
            ;;
    esac
    echo
}

# Enhanced error handling wrapper
handle_error() {
    local exit_code=$?
    local error_type="$1"
    local context="${2:-}"
    
    if [ $exit_code -ne 0 ]; then
        print_error "Operation failed!"
        explain_error "$error_type" "$context"
        pause_for_user
        return $exit_code
    fi
    return 0
}

# Function to check dependencies
check_dependencies() {
    local missing_deps=()
    
    print_status "Checking system dependencies..."
    
    if ! command_exists python3; then
        missing_deps+=("python3")
    fi
    
    if ! command_exists pip3; then
        missing_deps+=("pip3")
    fi
    
    if ! command_exists psql; then
        missing_deps+=("postgresql")
    fi
    
    if ! command_exists redis-server; then
        missing_deps+=("redis-server")
    fi
    
    if [ ${#missing_deps[@]} -gt 0 ]; then
        print_error "Missing required dependencies!"
        for dep in "${missing_deps[@]}"; do
            echo "  - $dep"
            explain_error "dependency_missing" "$dep"
        done
        return 1
    else
        print_success "All system dependencies are installed!"
    fi
    return 0
}

# Function to create/activate virtual environment
setup_virtualenv() {
    if [ ! -d "$VENV_NAME" ]; then
        print_status "Creating Python virtual environment..."
        python3 -m venv "$VENV_NAME"
        print_success "Virtual environment created!"
    else
        print_success "Virtual environment already exists!"
    fi
    
    print_status "Activating virtual environment..."
    source "$VENV_NAME/bin/activate"
    
    # Upgrade pip and install requirements
    print_status "Installing/updating Python dependencies..."
    pip install --upgrade pip
    pip install -r requirements.txt
    
    print_success "Virtual environment ready!"
}

# Function to create local settings
create_local_settings() {
    if [ ! -f "$LOCAL_SETTINGS_FILE" ]; then
        print_status "Creating local development settings..."
        cat > "$LOCAL_SETTINGS_FILE" << 'EOF'
# Local development settings
# This file overrides settings.py for local development

from .settings import *
import os

# Database configuration for local development
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'news_trader',
        'USER': 'news_trader',
        'PASSWORD': 'news_trader',
        'HOST': 'localhost',
        'PORT': '5432',
    }
}

# Redis configuration for local development (WebSocket support)
CELERY_BROKER_URL = 'redis://localhost:6379/0'
CELERY_RESULT_BACKEND = 'redis://localhost:6379/0'

# WebSocket Channel Layers - FIXED for local development
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.pubsub.RedisPubSubChannelLayer',
        'CONFIG': {
            'hosts': [('localhost', 6379)],
        },
    },
}

# Local development specific settings
DEBUG = True
ALLOWED_HOSTS = ['localhost', '127.0.0.1', '0.0.0.0', '*']

# Ensure ASGI application is configured for WebSocket support
ASGI_APPLICATION = 'news_trader.asgi.application'

# Use local static files
STATIC_URL = '/static/'
STATICFILES_DIRS = [
    BASE_DIR / "static",
]

# WebSocket specific settings for local development
WEBSOCKET_URL = 'ws://localhost:8000/ws/dashboard/'

# Ensure Django Channels can find Redis
import redis
try:
    # Test Redis connection
    r = redis.Redis(host='localhost', port=6379, db=0, socket_connect_timeout=1)
    r.ping()
except:
    # Fallback to in-memory if Redis is not available
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels.layers.InMemoryChannelLayer',
        }
    }
EOF
        print_success "Created $LOCAL_SETTINGS_FILE with WebSocket support"
    else
        print_success "Local settings file already exists"
        # Check if it needs updating for WebSocket support
        if ! grep -q "CHANNEL_LAYERS" "$LOCAL_SETTINGS_FILE"; then
            print_warning "Local settings file exists but may need WebSocket configuration updates."
            read -p "Do you want to recreate it with WebSocket support? (y/N): " -n 1 -r
            echo
            if [[ $REPLY =~ ^[Yy]$ ]]; then
                rm "$LOCAL_SETTINGS_FILE"
                create_local_settings
            fi
        fi
    fi
}

# Function to setup environment file
setup_env_file() {
    if [ ! -f "$ENV_FILE" ]; then
        print_warning ".env file not found. Creating template..."
        cat > "$ENV_FILE" << 'EOF'
# Trading API Keys
ALPACA_API_KEY=YOUR_ALPACA_API_KEY
ALPACA_SECRET_KEY=YOUR_ALPACA_SECRET_KEY

# LLM API Keys
OPENAI_API_KEY=YOUR_OPENAI_API_KEY

# News API Keys
NEWSAPI_API_KEY=YOUR_NEWSAPI_API_KEY

# Django Settings
DEBUG=True
SECRET_KEY=django-insecure-dev-key-change-in-production
DJANGO_SETTINGS_MODULE=news_trader.local_settings

# Database
DB_NAME=news_trader
DB_USER=news_trader
DB_PASSWORD=news_trader
DB_HOST=localhost
DB_PORT=5432
EOF
        print_warning "Please edit $ENV_FILE with your actual API keys."
        echo
        read -p "Do you want to edit the .env file now? (y/N): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            ${EDITOR:-nano} "$ENV_FILE"
        fi
    else
        print_success ".env file found."
    fi
    
    # Set Django settings module for local development
    export DJANGO_SETTINGS_MODULE=news_trader.local_settings
}

# Function to check if PostgreSQL is running
check_postgresql() {
    if ! pg_isready -h localhost -p 5432 >/dev/null 2>&1; then
        print_error "PostgreSQL is not running!"
        explain_error "postgresql_not_running"
        return 1
    fi
    return 0
}

# Function to start PostgreSQL automatically
start_postgresql() {
    print_status "Attempting to start PostgreSQL..."
    
    # Try different methods based on system
    if command_exists brew; then
        # macOS with Homebrew
        print_process "Starting PostgreSQL with Homebrew..."
        if brew services start postgresql@14 >/dev/null 2>&1 || brew services start postgresql >/dev/null 2>&1; then
            print_success "PostgreSQL started with Homebrew"
            # Wait a moment for service to be ready
            sleep 3
            return 0
        else
            print_warning "Failed to start PostgreSQL with Homebrew, trying manual start..."
        fi
    fi
    
    # Try manual start with pg_ctl
    if command_exists pg_ctl; then
        local data_dir=""
        # Common PostgreSQL data directories
        for dir in "/usr/local/var/postgres" "/opt/homebrew/var/postgres" "/var/lib/postgresql/data" "/usr/local/pgsql/data"; do
            if [ -d "$dir" ]; then
                data_dir="$dir"
                break
            fi
        done
        
        if [ -n "$data_dir" ]; then
            print_process "Starting PostgreSQL manually with data directory: $data_dir"
            if pg_ctl -D "$data_dir" -l "$data_dir/postgresql.log" start >/dev/null 2>&1; then
                print_success "PostgreSQL started manually"
                sleep 3
                return 0
            fi
        fi
    fi
    
    # Try systemctl (Linux)
    if command_exists systemctl; then
        print_process "Starting PostgreSQL with systemctl..."
        if sudo systemctl start postgresql >/dev/null 2>&1; then
            print_success "PostgreSQL started with systemctl"
            sleep 3
            return 0
        fi
    fi
    
    print_error "Failed to start PostgreSQL automatically"
    return 1
}

# Function to check if Redis is running
check_redis() {
    if ! redis-cli ping >/dev/null 2>&1; then
        print_error "Redis is not running!"
        explain_error "redis_not_running"
        return 1
    fi
    return 0
}

# Function to start Redis automatically
start_redis() {
    print_status "Attempting to start Redis..."
    
    # Try different methods based on system
    if command_exists brew; then
        # macOS with Homebrew
        print_process "Starting Redis with Homebrew..."
        if brew services start redis >/dev/null 2>&1; then
            print_success "Redis started with Homebrew"
            # Wait a moment for service to be ready
            sleep 2
            return 0
        else
            print_warning "Failed to start Redis with Homebrew, trying manual start..."
        fi
    fi
    
    # Try manual start with redis-server
    if command_exists redis-server; then
        print_process "Starting Redis manually..."
        if redis-server --daemonize yes >/dev/null 2>&1; then
            print_success "Redis started manually"
            sleep 2
            return 0
        fi
    fi
    
    # Try systemctl (Linux)
    if command_exists systemctl; then
        print_process "Starting Redis with systemctl..."
        if sudo systemctl start redis >/dev/null 2>&1 || sudo systemctl start redis-server >/dev/null 2>&1; then
            print_success "Redis started with systemctl"
            sleep 2
            return 0
        fi
    fi
    
    print_error "Failed to start Redis automatically"
    return 1
}

# Function to check if a port is in use
check_port_in_use() {
    local port="$1"
    lsof -i ":$port" >/dev/null 2>&1
}

# Function to get processes using a port
get_port_processes() {
    local port="$1"
    lsof -i ":$port" 2>/dev/null | awk 'NR>1 {print $2}' | sort -u
}

# Function to get process info for a port
get_port_process_info() {
    local port="$1"
    lsof -i ":$port" 2>/dev/null | awk 'NR>1 {printf "%s (PID: %s)\n", $1, $2}' | sort -u
}

# Function to kill processes using a port
kill_port_processes() {
    local port="$1"
    local pids
    pids=$(get_port_processes "$port")
    
    if [ -n "$pids" ]; then
        print_warning "Killing processes using port $port..."
        for pid in $pids; do
            if kill -0 "$pid" 2>/dev/null; then
                print_process "Killing process $pid"
                kill "$pid" 2>/dev/null || kill -9 "$pid" 2>/dev/null
            fi
        done
        sleep 2
        return 0
    else
        return 1
    fi
}

# Function to check all required ports
check_required_ports() {
    local conflicts=()
    local django_port=8000
    local postgres_port=5432
    local redis_port=6379
    
    print_status "Checking required ports..."
    
    # Check Django port (8000)
    if check_port_in_use "$django_port"; then
        local process_info
        process_info=$(get_port_process_info "$django_port")
        print_warning "Port $django_port (Django) is in use by: $process_info"
        conflicts+=("$django_port")
    else
        print_success "Port $django_port (Django) is available"
    fi
    
    # Check PostgreSQL port (5432) - but don't consider it a conflict if it's our expected service
    if check_port_in_use "$postgres_port"; then
        if ! check_postgresql >/dev/null 2>&1; then
            local process_info
            process_info=$(get_port_process_info "$postgres_port")
            print_warning "Port $postgres_port (PostgreSQL) is in use but PostgreSQL service is not responding: $process_info"
            conflicts+=("$postgres_port")
        else
            print_success "Port $postgres_port (PostgreSQL) is in use by expected PostgreSQL service"
        fi
    else
        print_error "Port $postgres_port (PostgreSQL) is not in use - PostgreSQL is not running"
        return 1
    fi
    
    # Check Redis port (6379) - but don't consider it a conflict if it's our expected service
    if check_port_in_use "$redis_port"; then
        if ! check_redis >/dev/null 2>&1; then
            local process_info
            process_info=$(get_port_process_info "$redis_port")
            print_warning "Port $redis_port (Redis) is in use but Redis service is not responding: $process_info"
            conflicts+=("$redis_port")
        else
            print_success "Port $redis_port (Redis) is in use by expected Redis service"
        fi
    else
        print_error "Port $redis_port (Redis) is not in use - Redis is not running"
        return 1
    fi
    
    # Handle conflicts
    if [ ${#conflicts[@]} -gt 0 ]; then
        echo
        print_warning "Found port conflicts that need to be resolved:"
        for port in "${conflicts[@]}"; do
            local process_info
            process_info=$(get_port_process_info "$port")
            echo "  - Port $port: $process_info"
            explain_error "port_conflict" "$port"
        done
        
        read -p "Do you want to automatically kill these processes? (y/N): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            for port in "${conflicts[@]}"; do
                kill_port_processes "$port"
            done
            
            # Verify ports are now free
            sleep 1
            local still_blocked=()
            for port in "${conflicts[@]}"; do
                if check_port_in_use "$port"; then
                    still_blocked+=("$port")
                fi
            done
            
            if [ ${#still_blocked[@]} -gt 0 ]; then
                print_error "Some ports are still in use: ${still_blocked[*]}"
                for port in "${still_blocked[@]}"; do
                    explain_error "port_conflict" "$port"
                done
                return 1
            else
                print_success "All port conflicts resolved!"
            fi
        else
            print_error "Cannot start services with port conflicts."
            for port in "${conflicts[@]}"; do
                explain_error "port_conflict" "$port"
            done
            return 1
        fi
    fi
    
    return 0
}

# Function to setup database
setup_database() {
    print_status "Setting up local database..."
    
    # Ensure PostgreSQL is running
    if ! check_postgresql; then
        print_warning "PostgreSQL is not running and is required for database setup."
        read -p "Would you like to start PostgreSQL automatically? (y/N): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            if ! start_postgresql; then
                print_error "Failed to start PostgreSQL. Please start it manually and try again."
                return 1
            fi
            # Verify it started successfully
            if ! check_postgresql; then
                print_error "PostgreSQL started but is not responding. Please check the service status."
                return 1
            fi
        else
            print_error "PostgreSQL is required for database setup. Please start it manually."
            return 1
        fi
    fi
    
    # Check if database exists
    if ! psql -h localhost -U "$USER" -lqt | cut -d \| -f 1 | grep -qw news_trader; then
        print_status "Creating database and user..."
        
        # Create database and user
        psql -h localhost -U "$USER" -d postgres << EOF
CREATE USER news_trader WITH PASSWORD 'news_trader';
CREATE DATABASE news_trader OWNER news_trader;
GRANT ALL PRIVILEGES ON DATABASE news_trader TO news_trader;
EOF
        print_success "Database created!"
    else
        print_success "Database already exists"
    fi
    
    # Run migrations
    print_status "Running Django migrations..."
    source "$VENV_NAME/bin/activate"
    python manage.py migrate
    
    # Create superuser if it doesn't exist
    print_status "Creating superuser (admin/admin)..."
    python manage.py shell << 'EOF'
from django.contrib.auth import get_user_model
User = get_user_model()
if not User.objects.filter(username='admin').exists():
    User.objects.create_superuser('admin', 'admin@example.com', 'admin')
    print('Superuser created: admin/admin')
else:
    print('Superuser already exists')
EOF
    
    # Collect static files
    print_status "Collecting static files..."
    python manage.py collectstatic --noinput
    
    print_success "Database setup completed!"
}

# Function to start services
start_services() {
    create_directories
    
    # Check and start PostgreSQL if needed
    if ! check_postgresql; then
        print_warning "PostgreSQL is not running."
        read -p "Would you like to start PostgreSQL automatically? (y/N): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            if ! start_postgresql; then
                print_error "Failed to start PostgreSQL. Please start it manually and try again."
                return 1
            fi
            # Verify it started successfully
            if ! check_postgresql; then
                print_error "PostgreSQL started but is not responding. Please check the service status."
                return 1
            fi
        else
            print_error "PostgreSQL is required to run the application. Please start it manually."
            return 1
        fi
    fi
    
    # Check and start Redis if needed
    if ! check_redis; then
        print_warning "Redis is not running."
        read -p "Would you like to start Redis automatically? (y/N): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            if ! start_redis; then
                print_error "Failed to start Redis. Please start it manually and try again."
                return 1
            fi
            # Verify it started successfully
            if ! check_redis; then
                print_error "Redis started but is not responding. Please check the service status."
                return 1
            fi
        else
            print_error "Redis is required for WebSocket functionality. Please start it manually."
            return 1
        fi
    fi
    
    # Check for port conflicts and resolve them
    if ! check_required_ports; then
        print_error "Cannot start services due to port conflicts."
        return 1
    fi
    
    source "$VENV_NAME/bin/activate"
    export DJANGO_SETTINGS_MODULE=news_trader.local_settings
    
    print_status "Starting local development services..."
    
    # Start Django development server with ASGI (WebSocket support)
    print_process "Starting Django ASGI server (with WebSocket support) on http://localhost:8000"
    daphne -b 0.0.0.0 -p 8000 news_trader.asgi:application > "$LOGS_DIR/django.log" 2>&1 &
    echo $! > "$PID_DIR/django.pid"
    
    # Start Celery worker
    print_process "Starting Celery worker..."
    celery -A news_trader worker -l info > "$LOGS_DIR/celery_worker.log" 2>&1 &
    echo $! > "$PID_DIR/celery_worker.pid"
    
    # Start Celery beat
    print_process "Starting Celery beat scheduler..."
    celery -A news_trader beat -l info > "$LOGS_DIR/celery_beat.log" 2>&1 &
    echo $! > "$PID_DIR/celery_beat.pid"
    
    print_status "Waiting for services to start..."
    sleep 5
    
    print_success "All services started!"
    show_detailed_status
}

# Function to stop services
stop_services() {
    print_status "Stopping local services..."
    
    # Stop all processes
    for pid_file in "$PID_DIR"/*.pid; do
        if [ -f "$pid_file" ]; then
            pid=$(cat "$pid_file")
            service_name=$(basename "$pid_file" .pid)
            
            if kill -0 "$pid" 2>/dev/null; then
                print_process "Stopping $service_name (PID: $pid)"
                kill "$pid"
                rm "$pid_file"
            else
                print_warning "$service_name was not running"
                rm "$pid_file"
            fi
        fi
    done
    
    print_success "All services stopped"
}

# Function to restart services
restart_services() {
    print_status "Restarting services..."
    stop_services
    sleep 2
    start_services
}

# Function to show detailed status
show_detailed_status() {
    clear_screen
    print_status "📊 Service Status Report"
    echo "=================================="
    
    # Check each service with health status
    local django_running=false
    for pid_file in "$PID_DIR"/*.pid; do
        if [ -f "$pid_file" ]; then
            pid=$(cat "$pid_file")
            service_name=$(basename "$pid_file" .pid)
            
            if kill -0 "$pid" 2>/dev/null; then
                case "$service_name" in
                    "django")
                        django_running=true
                        local health=$(get_service_health "django")
                        case "$health" in
                            "healthy")
                                echo -e "  ${GREEN}✓${NC} Django (PID: $pid) - ${GREEN}Healthy${NC}"
                                ;;
                            "responding")
                                echo -e "  ${YELLOW}~${NC} Django (PID: $pid) - ${YELLOW}Responding${NC}"
                                ;;
                            *)
                                echo -e "  ${RED}✗${NC} Django (PID: $pid) - ${RED}Unhealthy${NC}"
                                ;;
                        esac
                        ;;
                    *)
                        echo -e "  ${GREEN}✓${NC} $service_name (PID: $pid) - ${GREEN}Running${NC}"
                        ;;
                esac
            else
                echo -e "  ${RED}✗${NC} $service_name - ${RED}Not running${NC}"
                rm "$pid_file"
            fi
        fi
    done
    
    # Check external services
    if check_postgresql >/dev/null 2>&1; then
        echo -e "  ${GREEN}✓${NC} PostgreSQL - ${GREEN}Connected${NC}"
    else
        echo -e "  ${RED}✗${NC} PostgreSQL - ${RED}Not accessible${NC}"
    fi
    
    if check_redis >/dev/null 2>&1; then
        echo -e "  ${GREEN}✓${NC} Redis - ${GREEN}Connected${NC}"
    else
        echo -e "  ${RED}✗${NC} Redis - ${RED}Not accessible${NC}"
    fi
    
    # Check WebSocket health if Django is running
    if [ "$django_running" = true ]; then
        local ws_health=$(get_service_health "websocket")
        case "$ws_health" in
            "healthy")
                echo -e "  ${GREEN}✓${NC} WebSocket - ${GREEN}Connected${NC}"
                ;;
            "unhealthy")
                echo -e "  ${RED}✗${NC} WebSocket - ${RED}Failed${NC}"
                ;;
            "unknown")
                echo -e "  ${YELLOW}?${NC} WebSocket - ${YELLOW}Cannot test (Node.js not available)${NC}"
                ;;
        esac
    else
        echo -e "  ${RED}✗${NC} WebSocket - ${RED}Django not running${NC}"
    fi
    
    echo
    print_status "🌐 Service URLs:"
    echo "=================================="
    
    # Test URL accessibility
    local django_health=$(get_service_health "django")
    if [ "$django_health" = "healthy" ] || [ "$django_health" = "responding" ]; then
        echo -e "  ${GREEN}✓${NC} Django Admin:    http://localhost:8000/admin/ (admin/admin)"
        echo -e "  ${GREEN}✓${NC} Dashboard:       http://localhost:8000/dashboard/"
        echo -e "  ${GREEN}✓${NC} Test Page:       http://localhost:8000/test-page/"
        
        # Show WebSocket URL if healthy
        local ws_health=$(get_service_health "websocket")
        if [ "$ws_health" = "healthy" ]; then
            echo -e "  ${GREEN}✓${NC} WebSocket:       ws://localhost:8000/ws/dashboard/"
        else
            echo -e "  ${RED}✗${NC} WebSocket:       ws://localhost:8000/ws/dashboard/ (not working)"
        fi
    else
        echo -e "  ${RED}✗${NC} Django Admin:    http://localhost:8000/admin/ (not responding)"
        echo -e "  ${RED}✗${NC} Dashboard:       http://localhost:8000/dashboard/ (not responding)"
        echo -e "  ${RED}✗${NC} Test Page:       http://localhost:8000/test-page/ (not responding)"
        echo -e "  ${RED}✗${NC} WebSocket:       ws://localhost:8000/ws/dashboard/ (not responding)"
    fi
    
    echo -e "  ${BLUE}ℹ${NC} PostgreSQL:      localhost:5432 (news_trader/news_trader/news_trader)"
    echo -e "  ${BLUE}ℹ${NC} Redis:           localhost:6379"
    
    # Show detailed error explanations if services are unhealthy
    if [ "$django_health" = "unhealthy" ]; then
        echo
        explain_error "django_unhealthy"
    fi
    
    local ws_health=$(get_service_health "websocket")
    if [ "$ws_health" = "unhealthy" ] && [ "$django_running" = true ]; then
        echo
        explain_error "websocket_failed"
    fi
    
    echo
}

# Function to show status (simplified)
show_status() {
    show_detailed_status
}

# Function to show logs interactively
show_logs_interactive() {
    local service="${1:-}"
    
    if [ -z "$service" ]; then
        clear_screen
        print_menu "📋 Available Log Files:"
        echo "=================================="
        
        local log_files=()
        local count=1
        
        for log_file in "$LOGS_DIR"/*.log; do
            if [ -f "$log_file" ]; then
                local service_name=$(basename "$log_file" .log)
                log_files+=("$service_name")
                echo "  $count) $service_name"
                ((count++))
            fi
        done
        
        if [ ${#log_files[@]} -eq 0 ]; then
            print_warning "No log files found"
            pause_for_user
            return
        fi
        
        echo "  q) Back to main menu"
        echo
        
        while true; do
            read -p "Select log file to view (1-${#log_files[@]}, q): " choice
            
            if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le ${#log_files[@]} ]; then
                local selected_service="${log_files[$((choice-1))]}"
                show_logs "$selected_service"
                break
            elif [ "$choice" = "q" ] || [ "$choice" = "Q" ]; then
                break
            else
                print_error "Invalid choice. Please try again."
            fi
        done
    else
        show_logs "$service"
    fi
}

# Function to show logs
show_logs() {
    local service="${1:-}"
    
    if [ -n "$service" ]; then
        local log_file="$LOGS_DIR/${service}.log"
        if [ -f "$log_file" ]; then
            clear_screen
            print_status "📋 Showing logs for $service (Press Ctrl+C to stop)..."
            echo "=================================="
            tail -f "$log_file"
        else
            print_error "Log file for $service not found: $log_file"
            pause_for_user
        fi
    else
        show_logs_interactive
    fi
}

# Function to run Django shell
django_shell() {
    source "$VENV_NAME/bin/activate"
    export DJANGO_SETTINGS_MODULE=news_trader.local_settings
    clear_screen
    print_status "🐍 Opening Django Shell..."
    echo "=================================="
    python manage.py shell
}

# Function to run Django management commands
run_django_command() {
    source "$VENV_NAME/bin/activate"
    export DJANGO_SETTINGS_MODULE=news_trader.local_settings
    python manage.py "$@"
}

# Function to run tests
run_tests() {
    source "$VENV_NAME/bin/activate"
    export DJANGO_SETTINGS_MODULE=news_trader.local_settings
    clear_screen
    print_status "🧪 Running Tests..."
    echo "=================================="
    python manage.py test
    pause_for_user
}

# Function to reset database
reset_database() {
    print_warning "This will delete all data in the database!"
    read -p "Are you sure? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        print_status "Resetting database..."
        
        # Drop and recreate database
        psql -h localhost -U "$USER" -d postgres << EOF
DROP DATABASE IF EXISTS news_trader;
DROP USER IF EXISTS news_trader;
CREATE USER news_trader WITH PASSWORD 'news_trader';
CREATE DATABASE news_trader OWNER news_trader;
GRANT ALL PRIVILEGES ON DATABASE news_trader TO news_trader;
EOF
        
        setup_database
        print_success "Database reset completed!"
        pause_for_user
    fi
}

# Function to backup database
backup_database() {
    local backup_file="backup_$(date +%Y%m%d_%H%M%S).sql"
    print_status "Creating database backup: $backup_file"
    pg_dump -h localhost -U news_trader news_trader > "$backup_file"
    print_success "Database backed up to $backup_file"
    pause_for_user
}

# Function to cleanup
cleanup() {
    stop_services
    print_status "Cleaning up log and PID files..."
    rm -rf "$LOGS_DIR" "$PID_DIR"
    print_success "Cleanup completed!"
    pause_for_user
}

# Function to monitor services in real time
monitor_services() {
    while true; do
        show_detailed_status
        echo
        print_status "🔄 Auto-refreshing in 5 seconds... (Press Ctrl+C to stop)"
        sleep 5
    done
}

# Interactive main menu
interactive_menu() {
    while true; do
        clear_screen
        print_menu "🎛️  Main Menu"
        echo "=================================="
        echo "  1) 🚀 Start all services"
        echo "  2) 🛑 Stop all services"
        echo "  3) 🔄 Restart all services"
        echo "  4) 📊 Show detailed status"
        echo "  5) 🔍 Monitor services (real-time)"
        echo
        echo "  6) 📋 View logs"
        echo "  7) 🐍 Django shell"
        echo "  8) 🧪 Run tests"
        echo
        echo "  9) 🔧 Setup/Install"
        echo " 10) 🗄️  Database management"
        echo " 11) 🔍 Check ports"
        echo " 12) 🩺 Troubleshoot issues"
        echo " 13) 🧹 Cleanup"
        echo
        echo "  q) 🚪 Quit"
        echo
        
        read -p "Select an option (1-13, q): " choice
        echo
        
        case "$choice" in
            1)
                start_services
                pause_for_user
                ;;
            2)
                stop_services
                pause_for_user
                ;;
            3)
                restart_services
                pause_for_user
                ;;
            4)
                show_detailed_status
                pause_for_user
                ;;
            5)
                monitor_services
                ;;
            6)
                show_logs_interactive
                ;;
            7)
                django_shell
                ;;
            8)
                run_tests
                ;;
            9)
                setup_menu
                ;;
            10)
                database_menu
                ;;
            11)
                check_required_ports
                pause_for_user
                ;;
            12)
                troubleshoot_menu
                ;;
            13)
                cleanup
                ;;
            "q"|"Q")
                clear_screen
                print_success "👋 Goodbye!"
                exit 0
                ;;
            *)
                print_error "Invalid choice. Please try again."
                sleep 2
                ;;
        esac
    done
}

# Setup submenu
setup_menu() {
    while true; do
        clear_screen
        print_menu "🔧 Setup & Installation"
        echo "=================================="
        echo "  1) 🏗️  Complete setup (recommended)"
        echo "  2) 📦 Check dependencies"
        echo "  3) 🐍 Setup virtual environment"
        echo "  4) ⚙️  Create local settings"
        echo "  5) 📝 Setup environment file"
        echo "  6) 🗄️  Setup database"
        echo
        echo "  b) ⬅️  Back to main menu"
        echo
        
        read -p "Select an option (1-6, b): " choice
        echo
        
        case "$choice" in
            1)
                full_setup
                pause_for_user
                ;;
            2)
                check_dependencies
                pause_for_user
                ;;
            3)
                setup_virtualenv
                pause_for_user
                ;;
            4)
                create_local_settings
                pause_for_user
                ;;
            5)
                setup_env_file
                pause_for_user
                ;;
            6)
                setup_env_file
                setup_virtualenv
                setup_database
                pause_for_user
                ;;
            "b"|"B")
                break
                ;;
            *)
                print_error "Invalid choice. Please try again."
                sleep 2
                ;;
        esac
    done
}

# Database submenu
database_menu() {
    while true; do
        clear_screen
        print_menu "🗄️  Database Management"
        echo "=================================="
        echo "  1) 🔧 Setup database"
        echo "  2) 🔄 Reset database (deletes all data)"
        echo "  3) 💾 Backup database"
        echo "  4) 🔍 Test database connection"
        echo
        echo "  b) ⬅️  Back to main menu"
        echo
        
        read -p "Select an option (1-4, b): " choice
        echo
        
        case "$choice" in
            1)
                setup_env_file
                setup_virtualenv
                setup_database
                pause_for_user
                ;;
            2)
                reset_database
                ;;
            3)
                backup_database
                ;;
            4)
                if check_postgresql; then
                    print_success "PostgreSQL connection: OK"
                else
                    print_error "PostgreSQL connection: FAILED"
                fi
                pause_for_user
                ;;
            "b"|"B")
                break
                ;;
            *)
                print_error "Invalid choice. Please try again."
                sleep 2
                ;;
        esac
    done
}

# Troubleshoot submenu
troubleshoot_menu() {
    while true; do
        clear_screen
        print_menu "🩺 Troubleshoot Issues"
        echo "=================================="
        echo "  1) 🔍 Check all services health"
        echo "  2) 🌐 Test WebSocket connection"
        echo "  3) 🔗 Test database connection"
        echo "  4) 📡 Test Redis connection"
        echo "  5) 🚪 Check port conflicts"
        echo "  6) 📋 View all logs"
        echo "  7) 🔄 Restart all services"
        echo "  8) 🚀 Start PostgreSQL/Redis automatically"
        echo "  9) 🆘 Emergency cleanup"
        echo " 10) 📦 Recreate local settings"
        echo
        echo "  b) ⬅️  Back to main menu"
        echo
        
        read -p "Select an option (1-10, b): " choice
        echo
        
        case "$choice" in
            1)
                show_detailed_status
                pause_for_user
                ;;
            2)
                print_status "Testing WebSocket connection..."
                if cd "$(pwd)" && /opt/homebrew/bin/node -e "
const WebSocket = require('ws');
const ws = new WebSocket('ws://localhost:8000/ws/dashboard/');
ws.on('open', () => { 
    console.log('✅ WebSocket connection: SUCCESS');
    ws.close(); 
    process.exit(0); 
});
ws.on('error', (err) => { 
    console.log('❌ WebSocket connection: FAILED -', err.message);
    process.exit(1); 
});
setTimeout(() => { 
    console.log('⏰ WebSocket connection: TIMEOUT');
    process.exit(1); 
}, 3000);" 2>/dev/null; then
                    print_success "WebSocket is working perfectly!"
                else
                    print_error "WebSocket connection failed!"
                    explain_error "websocket_failed"
                fi
                pause_for_user
                ;;
            3)
                print_status "Testing database connection..."
                if check_postgresql; then
                    print_success "PostgreSQL connection: OK"
                    # Test actual database access
                    if command_exists psql; then
                        if psql -h localhost -U news_trader -d news_trader -c "SELECT 1;" >/dev/null 2>&1; then
                            print_success "Database access: OK"
                        else
                            print_error "Database access failed!"
                            explain_error "database_connection_failed"
                        fi
                    fi
                else
                    print_error "PostgreSQL connection failed!"
                fi
                pause_for_user
                ;;
            4)
                print_status "Testing Redis connection..."
                if check_redis; then
                    print_success "Redis connection: OK"
                    print_status "Redis info: $(redis-cli info server | grep redis_version | head -1)"
                else
                    print_error "Redis connection failed!"
                fi
                pause_for_user
                ;;
            5)
                check_required_ports
                pause_for_user
                ;;
            6)
                show_logs_interactive
                ;;
            7)
                print_warning "This will restart all services. Continue?"
                read -p "Restart all services? (y/N): " -n 1 -r
                echo
                if [[ $REPLY =~ ^[Yy]$ ]]; then
                    restart_services
                fi
                pause_for_user
                ;;
            8)
                print_status "Checking and starting required services..."
                
                # Check and start PostgreSQL
                if ! check_postgresql; then
                    print_warning "PostgreSQL is not running."
                    read -p "Start PostgreSQL automatically? (y/N): " -n 1 -r
                    echo
                    if [[ $REPLY =~ ^[Yy]$ ]]; then
                        if start_postgresql && check_postgresql; then
                            print_success "PostgreSQL started successfully!"
                        else
                            print_error "Failed to start PostgreSQL."
                        fi
                    fi
                else
                    print_success "PostgreSQL is already running."
                fi
                
                # Check and start Redis
                if ! check_redis; then
                    print_warning "Redis is not running."
                    read -p "Start Redis automatically? (y/N): " -n 1 -r
                    echo
                    if [[ $REPLY =~ ^[Yy]$ ]]; then
                        if start_redis && check_redis; then
                            print_success "Redis started successfully!"
                        else
                            print_error "Failed to start Redis."
                        fi
                    fi
                else
                    print_success "Redis is already running."
                fi
                
                pause_for_user
                ;;
            9)
                print_warning "Emergency cleanup will:"
                echo "• Stop all services"
                echo "• Clear all logs and PID files"
                echo "• Kill any processes on ports 8000, 5432, 6379"
                echo
                read -p "Proceed with emergency cleanup? (y/N): " -n 1 -r
                echo
                if [[ $REPLY =~ ^[Yy]$ ]]; then
                    stop_services
                    cleanup
                    # Force kill processes on required ports
                    for port in 8000 5432 6379; do
                        if check_port_in_use "$port"; then
                            print_status "Force cleaning port $port..."
                            kill_port_processes "$port"
                        fi
                    done
                    print_success "Emergency cleanup completed!"
                fi
                pause_for_user
                ;;
            10)
                print_warning "This will recreate local_settings.py with WebSocket support."
                read -p "Recreate local settings? (y/N): " -n 1 -r
                echo
                if [[ $REPLY =~ ^[Yy]$ ]]; then
                    rm -f "$LOCAL_SETTINGS_FILE"
                    create_local_settings
                    print_success "Local settings recreated! Restart services to apply changes."
                fi
                pause_for_user
                ;;
            "b"|"B")
                break
                ;;
            *)
                print_error "Invalid choice. Please try again."
                sleep 2
                ;;
        esac
    done
}

# Function for complete setup
full_setup() {
    print_status "🏗️  Starting complete setup..."
    echo
    
    check_dependencies || return 1
    create_directories
    setup_env_file
    create_local_settings
    setup_virtualenv
    
    # Check PostgreSQL and offer to start it
    local postgresql_ready=false
    if check_postgresql; then
        postgresql_ready=true
    else
        print_warning "PostgreSQL is not running and is needed for database setup."
        read -p "Would you like to start PostgreSQL automatically? (y/N): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            if start_postgresql && check_postgresql; then
                postgresql_ready=true
                print_success "PostgreSQL is now running!"
            else
                print_error "Failed to start PostgreSQL."
            fi
        fi
    fi
    
    # Check Redis and offer to start it
    local redis_ready=false
    if check_redis; then
        redis_ready=true
    else
        print_warning "Redis is not running and is needed for WebSocket functionality."
        read -p "Would you like to start Redis automatically? (y/N): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            if start_redis && check_redis; then
                redis_ready=true
                print_success "Redis is now running!"
            else
                print_error "Failed to start Redis."
            fi
        fi
    fi
    
    # Setup database if PostgreSQL is ready
    if [ "$postgresql_ready" = true ]; then
        setup_database
        if [ "$redis_ready" = true ]; then
            print_success "🎉 Complete setup finished! All services are ready."
            print_success "You can now start the application with: $0 start"
        else
            print_success "🎉 Setup completed! PostgreSQL is ready."
            print_warning "Redis is not running - WebSocket features will be limited."
        fi
    else
        print_warning "Setup completed, but PostgreSQL is not running."
        print_warning "Please start PostgreSQL manually before using the database features."
        if [ "$redis_ready" = false ]; then
            print_warning "Redis is also not running - please start it for WebSocket functionality."
        fi
    fi
}

# Function to show help
show_help() {
    cat << EOF
🚀 News Trader Local Development Manager

Usage: $0 [COMMAND] [OPTIONS]

SETUP COMMANDS:
    setup           Complete initial setup (venv, deps, database, local settings)
    deps            Check and install dependencies
    venv            Setup Python virtual environment
    db-setup        Setup local database

SERVICE COMMANDS:
    start           Start all local services
    stop            Stop all local services
    restart         Restart all local services
    status          Show service status and URLs
    check-ports     Check for port conflicts and optionally resolve them
    monitor         Monitor services in real-time
    start-db        Start PostgreSQL and Redis automatically

DATABASE COMMANDS:
    db-reset        Reset database (removes all data)
    db-backup       Create database backup

DEVELOPMENT COMMANDS:
    logs [SERVICE]  Show logs (django, celery_worker, celery_beat)
    shell           Open Django shell
    cmd COMMAND     Run Django management command
    test            Run tests

UTILITY COMMANDS:
    cleanup         Stop services and remove log/pid files
    interactive     Launch interactive menu (default if no command given)
    help            Show this help message

EXAMPLES:
    $0                          # Launch interactive menu
    $0 setup                    # Initial setup
    $0 start-db                 # Start PostgreSQL and Redis
    $0 start                    # Start development environment
    $0 check-ports              # Check for port conflicts
    $0 logs django              # Show Django logs
    $0 cmd createsuperuser      # Create Django superuser
    $0 db-backup                # Backup database

REQUIREMENTS:
    - Python 3.8+
    - PostgreSQL (running on localhost:5432)
    - Redis (running on localhost:6379)

INSTALLATION (macOS with Homebrew):
    brew install python postgresql redis
    brew services start postgresql redis

For other systems, install Python 3, PostgreSQL, and Redis using your package manager.
EOF
}

# Main script logic
main() {
    local command="${1:-interactive}"
    
    case "$command" in
        "setup")
            clear_screen
            full_setup
            pause_for_user
            ;;
        "deps")
            clear_screen
            check_dependencies
            pause_for_user
            ;;
        "venv")
            clear_screen
            setup_virtualenv
            pause_for_user
            ;;
        "start")
            clear_screen
            setup_env_file
            start_services
            pause_for_user
            ;;
        "stop")
            clear_screen
            stop_services
            pause_for_user
            ;;
        "restart")
            clear_screen
            restart_services
            pause_for_user
            ;;
        "status")
            show_detailed_status
            ;;
        "monitor")
            monitor_services
            ;;
        "start-db")
            clear_screen
            print_status "Starting database services..."
            
            # Start PostgreSQL
            if ! check_postgresql; then
                print_warning "PostgreSQL is not running."
                read -p "Start PostgreSQL automatically? (Y/n): " -n 1 -r
                echo
                if [[ ! $REPLY =~ ^[Nn]$ ]]; then
                    if start_postgresql && check_postgresql; then
                        print_success "PostgreSQL started successfully!"
                    else
                        print_error "Failed to start PostgreSQL."
                    fi
                fi
            else
                print_success "PostgreSQL is already running."
            fi
            
            # Start Redis
            if ! check_redis; then
                print_warning "Redis is not running."
                read -p "Start Redis automatically? (Y/n): " -n 1 -r
                echo
                if [[ ! $REPLY =~ ^[Nn]$ ]]; then
                    if start_redis && check_redis; then
                        print_success "Redis started successfully!"
                    else
                        print_error "Failed to start Redis."
                    fi
                fi
            else
                print_success "Redis is already running."
            fi
            
            pause_for_user
            ;;
        "check-ports")
            clear_screen
            check_required_ports
            pause_for_user
            ;;
        "db-setup")
            clear_screen
            setup_env_file
            setup_virtualenv
            setup_database
            pause_for_user
            ;;
        "db-reset")
            clear_screen
            reset_database
            ;;
        "db-backup")
            clear_screen
            backup_database
            ;;
        "logs")
            if [ -n "$2" ]; then
                show_logs "$2"
            else
                show_logs_interactive
            fi
            ;;
        "shell")
            django_shell
            ;;
        "cmd")
            shift
            run_django_command "$@"
            ;;
        "test")
            run_tests
            ;;
        "cleanup")
            clear_screen
            cleanup
            ;;
        "interactive")
            interactive_menu
            ;;
        "help"|"-h"|"--help")
            show_help
            ;;
        *)
            # If no valid command is given, start interactive mode
            interactive_menu
            ;;
    esac
}

# Check if script is being run directly
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi 