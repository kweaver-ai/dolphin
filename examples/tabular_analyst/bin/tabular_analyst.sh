#!/bin/bash

# Color definitions
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Supported file formats
SUPPORTED_FORMATS=("csv" "xlsx" "xls" "json" "parquet")

# Parameter validation
if [ -z "$1" ]; then
    echo -e "${RED}Error: Missing file path argument${NC}"
    echo ""
    echo "Usage: $0 <file_path>"
    echo ""
    echo "Examples:"
    echo "  $0 /path/to/data.xlsx"
    echo "  $0 ~/Documents/sales_data.csv"
    echo ""
    echo -e "Supported file formats: ${GREEN}${SUPPORTED_FORMATS[*]}${NC}"
    exit 1
fi

FILE_PATH="$1"

# Check if file exists
if [ ! -e "$FILE_PATH" ]; then
    echo -e "${RED}Error: File does not exist${NC}"
    echo "File path: $FILE_PATH"
    exit 1
fi

# Check if path is a file (not a directory)
if [ ! -f "$FILE_PATH" ]; then
    echo -e "${RED}Error: Path is not a file${NC}"
    echo "Path: $FILE_PATH"
    exit 1
fi

# Get file extension (convert to lowercase)
FILE_EXT="${FILE_PATH##*.}"
FILE_EXT_LOWER=$(echo "$FILE_EXT" | tr '[:upper:]' '[:lower:]')

# Check if file format is supported
FORMAT_SUPPORTED=false
for format in "${SUPPORTED_FORMATS[@]}"; do
    if [ "$FILE_EXT_LOWER" == "$format" ]; then
        FORMAT_SUPPORTED=true
        break
    fi
done

if [ "$FORMAT_SUPPORTED" = false ]; then
    echo -e "${RED}Error: Unsupported file format '.$FILE_EXT'${NC}"
    echo ""
    echo -e "Supported file formats: ${GREEN}${SUPPORTED_FORMATS[*]}${NC}"
    echo ""
    echo "Your file: $FILE_PATH"
    exit 1
fi

# Check if file is readable
if [ ! -r "$FILE_PATH" ]; then
    echo -e "${RED}Error: File is not readable${NC}"
    echo "File path: $FILE_PATH"
    echo "Please check file permissions"
    exit 1
fi

# All checks passed, display confirmation
echo -e "${GREEN}✓${NC} File validation passed"
echo "  File path: $FILE_PATH"
echo "  File format: .$FILE_EXT_LOWER"
echo ""

# Execute main program (with cli and lib extras for optional dependencies)
uv run --extra cli --extra lib ./bin/dolphin run --folder examples/tabular_analyst/ \
    --agent tabular_analyst \
    --config examples/tabular_analyst/config/global.yaml \
    --user_id tabular_analyst_user \
    --session_id tabular_analyst_session_6 \
    --skill_folder examples/tabular_analyst/skillkits/ \
    --no-explore_block_v2 \
    --interactive \
    --vv \
    --query "$FILE_PATH" \
    --reportpath "tabular_analyst_report.html"
