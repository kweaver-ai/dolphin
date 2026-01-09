#!/bin/bash
# ============================================================================
# Resource Skill Example - Launch Script
# ============================================================================
#
# This example demonstrates the ResourceSkillkit with self-contained skills.
# All skills are located in the example's own skills/ directory.
#
# Usage:
#   ./bin/skill_guided_coding.sh "I have a new product idea, help me brainstorm"
#   ./bin/skill_guided_coding.sh "As CTO, how should I assess our tech debt?"
#
# ============================================================================

set -e

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXAMPLE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${EXAMPLE_DIR}/../.." && pwd)"

# Check if config exists
CONFIG_FILE="${EXAMPLE_DIR}/config/global.yaml"
if [ ! -f "$CONFIG_FILE" ]; then
    echo "Error: Configuration file not found: $CONFIG_FILE"
    echo "Please copy from another example, e.g.:"
    echo "  cp ../tabular_analyst/config/global.yaml config/"
    exit 1
fi

# Check if query is provided
if [ -z "$1" ]; then
    echo "Usage: $0 <query>"
    echo ""
    echo "Examples:"
    echo "  $0 \"I have a new product idea, help me brainstorm\""
    echo "  $0 \"As CTO, how should I assess our tech debt?\""
    echo "  $0 \"Help me design a new feature for my mobile app\""
    echo ""
    echo "Available skills:"
    for skill_dir in "${EXAMPLE_DIR}/skills/"*/; do
        skill_name=$(basename "$skill_dir")
        # Extract description from SKILL.md if exists
        skill_file="${skill_dir}SKILL.md"
        if [ -f "$skill_file" ]; then
            desc=$(grep -A1 "^description:" "$skill_file" | head -1 | sed 's/^description: *//' | cut -c1-60)
            echo "  - ${skill_name}: ${desc}..."
        else
            echo "  - ${skill_name}"
        fi
    done
    exit 1
fi

# Run the agent - use example's own skills directory
cd "$PROJECT_ROOT"
uv run --extra cli --extra lib ./bin/dolphin run \
    --folder "${EXAMPLE_DIR}" \
    --agent skill_guided_assistant \
    --config "$CONFIG_FILE" \
    --query "$*" \
    --no-explore_block_v2 \
    --interactive
