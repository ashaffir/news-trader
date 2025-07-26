#!/bin/bash

# Function to display the main menu
display_menu() {
    clear
    echo "======================================="
    echo "        Docker Management Menu         "
    echo "======================================="
    echo "1. Restart ALL services (without build)"
    echo "2. Restart ALL services (with build)"
    echo "3. Restart INDIVIDUAL service (without build)"
    echo "4. Restart INDIVIDUAL service (with build)"
    echo "5. Check status of services"
    echo "6. Stop ALL services"
    echo "7. Stop INDIVIDUAL service"
    echo "8. Exit"
    echo "======================================="
    echo -n "Enter your choice: "
}

# Function to confirm an action
confirm_action() {
    read -p "$1 (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]
    then
        return 0 # True
    else
        return 1 # False
    fi
}

# Function to get a selected service from the user
get_selected_service() {
    SERVICES=$(docker-compose ps --services 2>/dev/null)
    if [ -z "$SERVICES" ]; then
        echo "No services found or running. Please ensure Docker Compose services are defined." >&2
        return 1
    fi

    echo "Available services:" >&2
    # Redirect select's output to /dev/tty (the terminal) to prevent it from being captured
    select SERVICE_CHOICE in $SERVICES; do
        if [ -n "$SERVICE_CHOICE" ]; then
            echo "$SERVICE_CHOICE" # This will be the actual return value of the function
            break
        else
            echo "Invalid selection. Please try again." >&2
        fi
    done </dev/tty >/dev/tty
    return 0
}

# Main script logic
while true; do
    display_menu
    read choice

    case $choice in
        1) # Restart ALL services (without build)
            echo "Restarting all services..."
            docker-compose restart
            echo "All services restarted."
            read -p "Press Enter to continue..."
            ;;
        2) # Restart ALL services (with build)
            if confirm_action "Are you sure you want to rebuild and restart ALL services? This might take a while."; then
                echo "Rebuilding and restarting all services..."
                docker-compose up -d --build
                echo "All services rebuilt and restarted."
            else
                echo "Operation cancelled."
            fi
            read -p "Press Enter to continue..."
            ;;
        3) # Restart INDIVIDUAL service (without build)
            SELECTED_SERVICE=$(get_selected_service)
            if [ $? -eq 0 ] && [ -n "$SELECTED_SERVICE" ]; then
                echo "Restarting $SELECTED_SERVICE..."
                docker-compose restart "$SELECTED_SERVICE"
                echo "$SELECTED_SERVICE restarted."
            else
                echo "No service selected or services not found."
            fi
            read -p "Press Enter to continue..."
            ;;
        4) # Restart INDIVIDUAL service (with build)
            SELECTED_SERVICE=$(get_selected_service)
            if [ $? -eq 0 ] && [ -n "$SELECTED_SERVICE" ]; then
                if confirm_action "Are you sure you want to rebuild and restart $SELECTED_SERVICE? This might take a while."; then
                    echo "Rebuilding and restarting $SELECTED_SERVICE..."
                    docker-compose up -d --build "$SELECTED_SERVICE"
                    echo "$SELECTED_SERVICE rebuilt and restarted."
                else
                    echo "Operation cancelled."
                fi
            else
                echo "No service selected or services not found."
            fi
            read -p "Press Enter to continue..."
            ;;
        5) # Check status of services
            echo "Checking service status:"
            docker-compose ps
            read -p "Press Enter to continue..."
            ;;
        6) # Stop ALL services
            if confirm_action "Are you sure you want to stop ALL services?"; then
                echo "Stopping all services..."
                docker-compose down
                echo "All services stopped."
            else
                echo "Operation cancelled."
            fi
            read -p "Press Enter to continue..."
            ;;
        7) # Stop INDIVIDUAL service
            SELECTED_SERVICE=$(get_selected_service)
            if [ $? -eq 0 ] && [ -n "$SELECTED_SERVICE" ]; then
                if confirm_action "Are you sure you want to stop $SELECTED_SERVICE?"; then
                    echo "Stopping $SELECTED_SERVICE..."
                    docker-compose stop "$SELECTED_SERVICE"
                    echo "$SELECTED_SERVICE stopped."
                else
                    echo "Operation cancelled."
                fi
            else
                echo "No service selected or services not found."
            fi
            read -p "Press Enter to continue..."
            ;;
        8) # Exit
            echo "Exiting Docker management script. Goodbye!"
            exit 0
            ;;
        *) # Invalid choice
            echo "Invalid choice. Please enter a number between 1 and 8."
            read -p "Press Enter to continue..."
            ;;
    esac
done