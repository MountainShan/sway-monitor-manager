#!/bin/bash

# Function to check if a command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Function to check Python package
check_python_package() {
    python3 -c "import $1" >/dev/null 2>&1
}

# Function to install package based on distribution
install_package() {
    if command_exists apt-get; then
        sudo apt-get install -y "$1"
    elif command_exists pacman; then
        sudo pacman -S --noconfirm "$1"
    elif command_exists dnf; then
        sudo dnf install -y "$1"
    else
        echo "Unsupported package manager. Please install $1 manually."
        exit 1
    fi
}

# Check and install system dependencies
echo "Checking system dependencies..."

# Check for sway
if ! command_exists sway; then
    echo "Warning: Sway is not installed. This tool requires Sway window manager."
    echo "Please install Sway before using this tool."
    read -p "Continue installation anyway? [y/N] " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Check for swaymsg
if ! command_exists swaymsg; then
    echo "Warning: swaymsg is not found. This tool requires swaymsg to function."
    echo "Please ensure Sway is properly installed."
    read -p "Continue installation anyway? [y/N] " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Check for Python 3
if ! command_exists python3; then
    echo "Installing Python 3..."
    install_package python3
fi

# Check for pip
if ! command_exists pip3; then
    echo "Installing pip3..."
    if command_exists apt-get; then
        install_package python3-pip
    elif command_exists pacman; then
        install_package python-pip
    elif command_exists dnf; then
        install_package python3-pip
    fi
fi

# Check for GTK dependencies
echo "Checking GTK dependencies..."
if command_exists apt-get; then
    sudo apt-get install -y python3-gi python3-gi-cairo gir1.2-gtk-4.0
elif command_exists pacman; then
    sudo pacman -S --noconfirm python-gobject gtk4
elif command_exists dnf; then
    sudo dnf install -y python3-gobject gtk4
fi

# Install additional dependencies
if command_exists apt-get; then
    sudo apt-get install -y python3-pyudev
elif command_exists pacman; then
    sudo pacman -S --noconfirm python-pyudev
elif command_exists dnf; then
    sudo dnf install -y python3-pyudev
fi

# Install the manager script
echo "Installing scripts..."
sudo install -m 755 sway_monitor_manager.py /usr/local/bin/sway-monitor-manager

# Install the daemon
sudo install -m 755 sway_monitor_daemon.py /usr/local/bin/sway-monitor-daemon

echo "Installation complete!"
echo "You can now:"
echo "1. Run 'sway-monitor-manager' or 'Sway Monitor Manager' in your applications menu to configure your monitors"
echo "2. Add exec --no-startup-id 'pkill sway-monitor-daemon & sleep 1 && sway-monitor-daemon to your sway config to start the daemon on login"
