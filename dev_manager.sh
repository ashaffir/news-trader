#!/bin/bash

# News Trader Local Development Manager - Fixed Version
# Proper hot reloading and service management

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
VENV_PATH="venv"
LOGS_DIR="logs"
PIDS_DIR="pids"

# Create necessary directories
mkdir -p "$LOGS_DIR" "$PIDS_DIR"

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

# Function to activate virtual environment
activate_venv() {
    if [ -d "$VENV_PATH" ]; then
        source "$VENV_PATH/bin/activate"
        export DJANGO_SETTINGS_MODULE=news_trader.settings
    else
        print_error "Virtual environment not found at $VENV_PATH"
        print_error "Please create it with: python3 -m venv $VENV_PATH && source $VENV_PATH/bin/activate && pip install -r requirements.txt"
        exit 1
    fi
}

# Function to check if service is running
is_running() {
    local pid_file="$PIDS_DIR/$1.pid"
    if [ -f "$pid_file" ]; then
        local pid=$(cat "$pid_file")
        if kill -0 "$pid" 2>/dev/null; then
            return 0
        else
            rm -f "$pid_file"
            return 1
        fi
    fi
    return 1
}

# Function to kill all processes by name (cleanup)
cleanup_processes() {
    print_status "Cleaning up any existing processes..."
    
    # Kill any existing Django/Celery processes
    pkill -f "manage.py runserver" 2>/dev/null || true

    pkill -f "celery -A news_trader" 2>/dev/null || true
    
    # Remove old PID files
    rm -f "$PIDS_DIR"/*.pid
    
    sleep 2
    print_success "Cleanup completed"
}

# Function to start all services with hot reloading
start_services() {
    print_status "Starting all local development services with hot reloading..."
    
    activate_venv
    cleanup_processes
    
    # Start Django development server with hot reloading
    if ! is_running "django"; then
        print_status "Starting Django development server with hot reloading..."
        DJANGO_SETTINGS_MODULE=news_trader.settings python manage.py runserver 0.0.0.0:8800 > "$LOGS_DIR/django.log" 2>&1 &
        echo $! > "$PIDS_DIR/django.pid"
        print_success "Django development server started (PID: $!)"
    else
        print_warning "Django server is already running"
    fi
    
    # Start single Celery worker with safe limits
    if ! is_running "celery_worker"; then
        print_status "Starting Celery worker..."
        CELERY_CONCURRENCY=${CELERY_CONCURRENCY:-2} \
        CELERY_MAX_TASKS_PER_CHILD=${CELERY_MAX_TASKS_PER_CHILD:-100} \
        CELERY_MAX_MEMORY_PER_CHILD=${CELERY_MAX_MEMORY_PER_CHILD:-300000} \
        CELERY_TASK_TIME_LIMIT=${CELERY_TASK_TIME_LIMIT:-180} \
        CELERY_TASK_SOFT_TIME_LIMIT=${CELERY_TASK_SOFT_TIME_LIMIT:-150} \
        celery -A news_trader worker -l info \
            --concurrency=${CELERY_CONCURRENCY} \
            --max-tasks-per-child=${CELERY_MAX_TASKS_PER_CHILD} \
            --max-memory-per-child=${CELERY_MAX_MEMORY_PER_CHILD} \
            --time-limit=${CELERY_TASK_TIME_LIMIT} \
            --soft-time-limit=${CELERY_TASK_SOFT_TIME_LIMIT} \
            > "$LOGS_DIR/celery_worker.log" 2>&1 &
        echo $! > "$PIDS_DIR/celery_worker.pid"
        print_success "Celery worker started (PID: $!)"
    else
        print_warning "Celery worker is already running"
    fi
    
    # Start Celery beat
    if ! is_running "celery_beat"; then
        print_status "Starting Celery beat scheduler..."
        celery -A news_trader beat -l info > "$LOGS_DIR/celery_beat.log" 2>&1 &
        echo $! > "$PIDS_DIR/celery_beat.pid"
        print_success "Celery beat started (PID: $!)"
    else
        print_warning "Celery beat is already running"
    fi
    
    sleep 3
    print_success "All services started with hot reloading!"
    print_success "🌐 Django server: http://localhost:8800"
    print_success "⚙️  Admin: http://localhost:8800/admin/"
    print_success "🧪 Test page: http://localhost:8800/test-page/"
    print_status "Code changes will automatically reload!"
}

# Function to stop all services
stop_services() {
    print_status "Stopping all local development services..."
    
    cleanup_processes
    
    local stopped_count=0
    
    for pid_file in "$PIDS_DIR"/*.pid; do
        if [ -f "$pid_file" ]; then
            local service_name=$(basename "$pid_file" .pid)
            local pid=$(cat "$pid_file")
            
            if kill -0 "$pid" 2>/dev/null; then
                print_status "Stopping $service_name (PID: $pid)..."
                kill "$pid"
                rm -f "$pid_file"
                stopped_count=$((stopped_count + 1))
            else
                print_warning "$service_name was not running"
                rm -f "$pid_file"
            fi
        fi
    done
    
    print_success "All services stopped and cleaned up"
}

# Function to restart services with code reload
restart_services() {
    print_status "Restarting all services..."
    stop_services
    sleep 2
    start_services
}

# Function to show service status
show_status() {
    echo -e "${BLUE}📊 Service Status:${NC}"
    echo "=================="
    
    local services=("django" "celery_worker" "celery_beat")
    local service_names=("Django Server" "Celery Worker" "Celery Beat")
    local running_count=0
    local i=0
    
    for service in "${services[@]}"; do
        if is_running "$service"; then
            local pid=$(cat "$PIDS_DIR/$service.pid")
            echo -e "  ${GREEN}✓${NC} ${service_names[$i]} (PID: $pid)"
            running_count=$((running_count + 1))
        else
            echo -e "  ${RED}✗${NC} ${service_names[$i]}"
        fi
        i=$((i + 1))
    done
    
    # Database status
    echo
    echo -e "${BLUE}🗄️  Database Status:${NC}"
    echo "==================="
    
    local db_check=$(DJANGO_SETTINGS_MODULE=news_trader.settings python manage.py shell -c "
from django.db import connection
from django.core.management.color import no_style
import sys
try:
    # Test the connection
    connection.ensure_connection()
    with connection.cursor() as cursor:
        cursor.execute('SELECT version();')
        version = cursor.fetchone()[0]
        cursor.execute('SELECT current_database();')
        db_name = cursor.fetchone()[0]
        cursor.execute('SELECT count(*) FROM information_schema.tables WHERE table_schema = %s;', ['public'])
        table_count = cursor.fetchone()[0]
    # Extract PostgreSQL version 
    pg_version = version.split(' on ')[0] if ' on ' in version else version.split(',')[0]
    print(f'✓|{db_name}|{table_count}|{pg_version}')
except Exception as e:
    error_msg = str(e).replace('\n', ' ').replace('|', ':')[:60]
    print(f'✗|{error_msg}|0|Unknown')
" 2>/dev/null)
    
    if [[ $db_check == ✓* ]]; then
        IFS='|' read -r status db_name table_count version <<< "$db_check"
        echo -e "  ${GREEN}✓${NC} PostgreSQL Connected"
        echo -e "     └─ Database: ${GREEN}$db_name${NC} (${GREEN}$table_count${NC} tables)"
        echo -e "     └─ Version: ${GREEN}$version${NC}"
    elif [[ $db_check == ✗* ]]; then
        IFS='|' read -r status error_info _ _ <<< "$db_check"
        echo -e "  ${RED}✗${NC} PostgreSQL Connection Failed"
        echo -e "     └─ ${RED}$error_info${NC}"
    else
        echo -e "  ${YELLOW}?${NC} PostgreSQL Status Unknown"
        echo -e "     └─ ${YELLOW}Unable to check connection${NC}"
    fi
    
    echo
    if [ $running_count -eq ${#services[@]} ]; then
        echo -e "  ${GREEN}🎉 All services running with hot reloading!${NC}"
        echo -e "  ${BLUE}🌐 Django: http://localhost:8800${NC}"
        echo -e "  ${BLUE}⚙️  Admin: http://localhost:8800/admin/${NC}"
        echo -e "  ${BLUE}🧪 Test: http://localhost:8800/test-page/${NC}"
    elif [ $running_count -gt 0 ]; then
        echo -e "  ${YELLOW}⚠️  $running_count of ${#services[@]} services running${NC}"
    else
        echo -e "  ${RED}❌ No services running${NC}"
        echo -e "  ${YELLOW}💡 Use 'start' to begin${NC}"
    fi
}

# Function to reload code without full restart
reload_code() {
    print_status "Reloading code changes..."
    
    if is_running "celery_worker"; then
        print_status "Restarting Celery worker for code changes..."
        local pid=$(cat "$PIDS_DIR/celery_worker.pid")
        kill -HUP "$pid" 2>/dev/null || {
            print_warning "Failed to reload Celery worker, restarting..."
            kill "$pid" 2>/dev/null || true
            rm -f "$PIDS_DIR/celery_worker.pid"
            
            sleep 1
            activate_venv
            celery -A news_trader worker -l info \
                --concurrency=${CELERY_CONCURRENCY:-2} \
                --max-tasks-per-child=${CELERY_MAX_TASKS_PER_CHILD:-100} \
                --max-memory-per-child=${CELERY_MAX_MEMORY_PER_CHILD:-300000} \
                --time-limit=${CELERY_TASK_TIME_LIMIT:-180} \
                --soft-time-limit=${CELERY_TASK_SOFT_TIME_LIMIT:-150} \
                > "$LOGS_DIR/celery_worker.log" 2>&1 &
            echo $! > "$PIDS_DIR/celery_worker.pid"
            print_success "Celery worker restarted (PID: $!)"
        }
    fi
    
    print_success "Code reloaded! Django auto-reloads automatically."
}

# Function to handle database migrations
migrate_database() {
    show_header
    echo -e "${BLUE}🗄️  Database Migration${NC}"
    echo "=============================="
    
    # Check if there are any pending model changes
    print_status "Checking for model changes..."
    
    # Run makemigrations to detect changes
    echo -e "${BLUE}Running makemigrations...${NC}"
    DJANGO_SETTINGS_MODULE=news_trader.settings python manage.py makemigrations
    local makemigrations_exit_code=$?
    
    if [ $makemigrations_exit_code -eq 0 ]; then
        echo
        print_status "Applying migrations..."
        DJANGO_SETTINGS_MODULE=news_trader.settings python manage.py migrate
        local migrate_exit_code=$?
        
        if [ $migrate_exit_code -eq 0 ]; then
            print_success "✅ Database migrations completed successfully!"
            
            # Show updated table count
            echo
            print_status "Updated database status:"
            local db_check=$(DJANGO_SETTINGS_MODULE=news_trader.settings python manage.py shell -c "
from django.db import connection
try:
    with connection.cursor() as cursor:
        cursor.execute('SELECT count(*) FROM information_schema.tables WHERE table_schema = %s;', ['public'])
        table_count = cursor.fetchone()[0]
    print(f'✓|{table_count}')
except Exception as e:
    print(f'✗|Error')
" 2>/dev/null)
            
            if [[ $db_check == ✓* ]]; then
                IFS='|' read -r status table_count <<< "$db_check"
                echo -e "  ${GREEN}✓${NC} Database now has ${GREEN}$table_count${NC} tables"
            fi
        else
            print_error "❌ Migration failed! Check the output above for errors."
        fi
    else
        print_warning "⚠️  No migrations needed or makemigrations failed."
    fi
    
    echo
    if [[ $1 != "no_pause" ]]; then
        pause
    fi
}

# Function to clear screen and show header
show_header() {
    clear
    echo -e "${BLUE}🚀 News Trader Development Manager${NC}"
    echo -e "${BLUE}=========================================${NC}"
    echo
}

# Function to pause and wait for user input
pause() {
    echo
    read -p "Press Enter to continue..." -r
    echo
}

# Function to show logs menu
logs_menu() {
    while true; do
        show_header
        print_status "📋 Log Viewer"
        echo "=============="
        echo
        
        # Show available log files
        local log_files=()
        local count=1
        
        for log_file in "$LOGS_DIR"/*.log; do
            if [ -f "$log_file" ]; then
                local log_name=$(basename "$log_file" .log)
                log_files+=("$log_name")
                echo "  $count) $log_name"
                count=$((count + 1))
            fi
        done
        
        if [ ${#log_files[@]} -eq 0 ]; then
            print_warning "No log files found. Start services first."
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
        
        echo "  r) 🔄 Refresh"
        echo "  b) ⬅️  Back to main menu"
        echo
        
        read -p "Select log to view (1-${#log_files[@]}, r, b): " choice
        
        case "$choice" in
            [1-9]*)
                if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le ${#log_files[@]} ]; then
                    local selected_service="${log_files[$((choice-1))]}"
                    show_header
                    print_status "📋 Viewing logs for $selected_service (Press Ctrl+C to return to menu)"
                    echo "=================================="
                    echo
                    tail -f "$LOGS_DIR/${selected_service}.log"
                else
                    print_error "Invalid choice. Please select a number between 1 and ${#log_files[@]}."
                    sleep 2
                fi
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

# Function to show interactive menu
interactive_menu() {
    while true; do
        show_header
        
        # Show current status
        show_status
        echo
        
        echo -e "${YELLOW}📋 Available Actions:${NC}"
        echo "========================"
        echo "  1) 🚀 Start all services"
        echo "  2) 🛑 Stop all services" 
        echo "  3) 🔄 Restart all services"
        echo "  4) 🔃 Reload code changes"
        echo "  5) 🗄️  Migrate database"
        echo "  6) 📊 Refresh status"
        echo "  7) 📋 View logs"
        echo "  8) 🧹 Cleanup processes"
        echo "  9) ❓ Show help"
        echo "  q) 🚪 Quit"
        echo
        
        read -p "Select an option (1-9, q): " choice
        echo
        
        case "$choice" in
            1)
                start_services
                pause
                ;;
            2)
                stop_services
                pause
                ;;
            3)
                restart_services
                pause
                ;;
            4)
                reload_code
                pause
                ;;
            5)
                migrate_database
                ;;
            6)
                # Just refresh - the loop will show status again
                ;;
            7)
                logs_menu
                ;;
            8)
                cleanup_processes
                pause
                ;;
            9)
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

# Function to show help
show_help() {
    echo "News Trader Development Manager"
    echo "===================================="
    echo
    echo "Usage: $0 [command]"
    echo
    echo "Interactive Mode (default):"
    echo "  $0                    Launch interactive menu"
    echo
    echo "Command Line Mode:"
    echo "  start     Start all services with hot reloading"
    echo "  stop      Stop all services and cleanup"
    echo "  restart   Restart all services"
    echo "  reload    Reload code changes without full restart"
    echo "  migrate   Run database migrations (makemigrations + migrate)"
    echo "  status    Show service status"
    echo "  cleanup   Kill any stuck processes"
    echo "  logs [service]  View logs (django, celery_worker, celery_beat)"
    echo "  help      Show this help"
    echo
    echo "Examples:"
    echo "  $0                    # Interactive mode"
    echo "  $0 start              # Start services"
    echo "  $0 logs django        # View Django logs"
    echo "  $0 restart            # Restart services"
    echo
    echo "Hot reloading enabled:"
    echo "  - Django auto-reloads on code changes"
    echo "  - Use 'reload' command for Celery changes"
}

# Main script logic
if [ $# -eq 0 ]; then
    # No arguments provided - start interactive mode
    interactive_menu
else
    # Arguments provided - use command line mode
    case "$1" in
        "start")
            start_services
            ;;
        "stop")
            stop_services
            ;;
        "restart")
            restart_services
            ;;
        "status")
            show_status
            ;;
        "reload")
            reload_code
            ;;
        "migrate")
            migrate_database
            ;;
        "cleanup")
            cleanup_processes
            ;;
        "logs")
            if [ -n "$2" ]; then
                tail -f "$LOGS_DIR/$2.log"
            else
                echo "Available logs:"
                ls -1 "$LOGS_DIR"/*.log 2>/dev/null | xargs -I{} basename {} .log || echo "No logs found"
            fi
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