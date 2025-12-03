#!/usr/bin/env bash
# =============================================================================
# aX Agent Studio - Automated Installation Script
# =============================================================================
# This script automates the setup process for aX Agent Studio:
# - Installs uv (Python package manager)
# - Creates virtual environment
# - Installs dependencies from pyproject.toml
# - Sets up configuration files
# - Creates necessary directories
#
# Supported platforms: macOS, Linux, Windows (WSL)
# =============================================================================

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Helper functions
print_step() {
    echo -e "${BLUE}==>${NC} $1"
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

# Detect OS
detect_os() {
    case "$(uname -s)" in
        Darwin*)
            OS="macOS"
            ;;
        Linux*)
            OS="Linux"
            ;;
        MINGW*|MSYS*|CYGWIN*)
            OS="Windows"
            ;;
        *)
            OS="Unknown"
            ;;
    esac
    print_success "Detected OS: $OS"
}

# Check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Install uv package manager
install_uv() {
    print_step "Checking for uv installation..."

    if command_exists uv; then
        print_success "uv is already installed ($(uv --version))"
        return 0
    fi

    print_step "Installing uv..."

    if [[ "$OS" == "Windows" ]]; then
        print_error "Please install uv manually on Windows: https://github.com/astral-sh/uv"
        exit 1
    else
        # Install uv using the official installer
        curl -LsSf https://astral.sh/uv/install.sh | sh

        # Add uv to PATH for current session
        export PATH="$HOME/.cargo/bin:$PATH"

        if command_exists uv; then
            print_success "uv installed successfully ($(uv --version))"
        else
            print_error "Failed to install uv. Please install manually: https://github.com/astral-sh/uv"
            exit 1
        fi
    fi
}

# Create virtual environment
create_venv() {
    print_step "Creating virtual environment..."

    if [ -d ".venv" ]; then
        print_warning "Virtual environment already exists at .venv"
        read -p "Do you want to recreate it? (y/N): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            rm -rf .venv
            print_step "Removed existing virtual environment"
        else
            print_success "Using existing virtual environment"
            return 0
        fi
    fi

    uv venv .venv
    print_success "Virtual environment created at .venv"
}

# Install dependencies
install_dependencies() {
    print_step "Installing dependencies from pyproject.toml..."

    # Activate virtual environment
    if [[ "$OS" == "Windows" ]]; then
        source .venv/Scripts/activate
    else
        source .venv/bin/activate
    fi

    # Install dependencies using uv
    uv pip install -e ".[dev]"

    print_success "Dependencies installed successfully"
}

# Setup configuration files
setup_config() {
    print_step "Setting up configuration files..."

    # Check for config.yaml
    if [ -f "config.yaml" ]; then
        print_warning "config.yaml already exists"
    elif [ -f "config.yaml.example" ]; then
        cp config.yaml.example config.yaml
        print_success "Created config.yaml from example"
        print_warning "Please review and update config.yaml with your settings"
    else
        print_warning "No config.yaml.example found - you'll need to create config.yaml manually"
    fi

    # Check for .env
    if [ -f ".env" ]; then
        print_warning ".env already exists"
    elif [ -f ".env.example" ]; then
        cp .env.example .env
        print_success "Created .env from example"
        print_warning "Please update .env with your API keys"
    elif [ -f ".env.sample" ]; then
        cp .env.sample .env
        print_success "Created .env from sample"
        print_warning "Please update .env with your API keys"
    else
        print_warning "No .env example found - you may need to create .env manually"
    fi
}

# Create necessary directories
create_directories() {
    print_step "Creating necessary directories..."

    directories=("data" "logs" "configs/agents")

    for dir in "${directories[@]}"; do
        if [ ! -d "$dir" ]; then
            mkdir -p "$dir"
            print_success "Created directory: $dir"
        else
            print_success "Directory already exists: $dir"
        fi
    done
}

# Verify installation
verify_installation() {
    print_step "Verifying installation..."

    # Activate virtual environment
    if [[ "$OS" == "Windows" ]]; then
        source .venv/Scripts/activate
    else
        source .venv/bin/activate
    fi

    # Check if main module can be imported
    if python -c "import ax_agent_studio" 2>/dev/null; then
        print_success "ax_agent_studio module can be imported"
    else
        print_error "Failed to import ax_agent_studio module"
        return 1
    fi

    # Check if CLI is available
    if command_exists ax-agent-studio; then
        print_success "ax-agent-studio CLI is available"
    else
        print_warning "CLI command not found - you may need to activate the virtual environment"
    fi
}

# Display next steps
show_next_steps() {
    echo ""
    echo -e "${GREEN}==============================================================================${NC}"
    echo -e "${GREEN}Installation Complete!${NC}"
    echo -e "${GREEN}==============================================================================${NC}"
    echo ""
    echo "Next steps:"
    echo ""
    echo "1. Activate the virtual environment:"
    if [[ "$OS" == "Windows" ]]; then
        echo -e "   ${BLUE}source .venv/Scripts/activate${NC}"
    else
        echo -e "   ${BLUE}source .venv/bin/activate${NC}"
    fi
    echo ""
    echo "2. Review and update configuration files:"
    echo -e "   ${BLUE}config.yaml${NC} - Main configuration"
    echo -e "   ${BLUE}.env${NC} - API keys and secrets"
    echo ""
    echo "3. Start the dashboard:"
    echo -e "   ${BLUE}python -m ax_agent_studio.dashboard${NC}"
    echo ""
    echo "4. Or run agents directly:"
    echo -e "   ${BLUE}ax-agent-studio --help${NC}"
    echo ""
    echo "For more information, see README.md"
    echo ""
}

# Main installation flow
main() {
    echo ""
    echo -e "${BLUE}==============================================================================${NC}"
    echo -e "${BLUE}aX Agent Studio - Automated Setup${NC}"
    echo -e "${BLUE}==============================================================================${NC}"
    echo ""

    # Check if we're in the right directory
    if [ ! -f "pyproject.toml" ]; then
        print_error "pyproject.toml not found. Please run this script from the ax-agent-studio root directory."
        exit 1
    fi

    detect_os
    echo ""

    install_uv
    echo ""

    create_venv
    echo ""

    install_dependencies
    echo ""

    setup_config
    echo ""

    create_directories
    echo ""

    verify_installation
    echo ""

    show_next_steps
}

# Run main function
main
