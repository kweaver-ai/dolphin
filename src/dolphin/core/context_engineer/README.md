# ContextEngineer

A Python package for optimizing context management in large language models through token budgeting and dynamic context optimization.

## Features

- **Token Budget Management**: Intelligent allocation of tokens across context buckets
- **Dynamic Context Optimization**: Select, compress, and reorder information to maximize relevance
- **Position-Aware Assembly**: Mitigate "Lost in the Middle" effect through strategic placement
- **Multiple Compression Strategies**: Extractive, abstractive, and signature-only compression
- **Policy-Based Configuration**: Task-specific optimization strategies
- **Extensible Architecture**: Custom tokenizers, compressors, and policies



## Quick Start

```python
from context_engineer import BudgetManager, ContextAssembler, TokenizerService, Compressor
from context_engineer.config.settings import get_default_config

# Load default configuration
config = get_default_config()

# Initialize components
tokenizer = TokenizerService()
budget_manager = BudgetManager(tokenizer)
compressor = Compressor(tokenizer)
assembler = ContextAssembler(tokenizer, compressor)

# Configure buckets from config
budget_manager.configure_buckets(config.buckets)

# Define content sections
content_sections = {
    "system": "You are a helpful AI assistant.",
    "task": "Help the user with their question.",
    "history": "Previous conversation about weather patterns.",
    "rag": "Retrieved information about current weather conditions."
}

# Allocate budget
allocations = budget_manager.allocate_budget(
    model_context_limit=8000,
    output_budget=1200,
    content_scores={"system": 1.0, "task": 0.9, "history": 0.6, "rag": 0.8}
)

# Assemble context
result = assembler.assemble_context(
    content_sections=content_sections,
    budget_allocations=allocations,
    placement_policy=config.get_default_policy().placement,
    bucket_configs=config.buckets
)

print(f"Assembled context: {result.total_tokens} tokens")
print(f"Sections: {[s.name for s in result.sections]}")
```

## Define Content Sections

Each section type serves a specific purpose in the context architecture. Here's a comprehensive example showing detailed content for each section type:

### Section Types and Examples

```python
# Comprehensive content sections example
content_sections = {
    # SYSTEM: Core behavioral instructions and constraints
    "system": """You are an advanced AI assistant specializing in data analysis and visualization. 
    Your responses should be accurate, well-structured, and include relevant visualizations when appropriate. 
    Always verify data integrity and cite sources when possible. 
    Follow ethical guidelines and avoid making unsupported claims.""",
    
    # TASK: Current user request and objectives
    "task": """Analyze the provided sales data for Q4 2023 and create a comprehensive report including:
    1. Revenue trends and seasonality patterns
    2. Top-performing products and regions
    3. Customer segmentation analysis
    4. Forecast for Q1 2024
    5. Actionable recommendations for improving sales performance""",
    
    # HISTORY: Previous conversation context
    "history": """User previously asked about data visualization best practices and was advised to:
    - Use appropriate chart types for different data (line for trends, bar for comparisons, scatter for correlations)
    - Include clear labels, titles, and legends
    - Consider color accessibility for colorblind users
    - Provide context and interpretation alongside visualizations
    User expressed preference for interactive dashboards over static charts""",
    
    # TOOLS: Available functions and their signatures
    "tools": """Available analysis tools:
    - analyze_sales_data(data: pd.DataFrame, metrics: List[str]) -> Dict: Calculate sales metrics and KPIs
    - create_visualization(data: pd.DataFrame, chart_type: str, options: Dict) -> Figure: Generate interactive charts
    - segment_customers(data: pd.DataFrame, method: str='kmeans') -> Dict: Customer segmentation analysis
    - forecast_sales(historical_data: pd.DataFrame, periods: int) -> Dict: Sales forecasting with confidence intervals
    - generate_report(analysis_results: Dict, format: str='markdown') -> str: Create formatted analysis report""",
    
    # MEMORY: Persistent user preferences and facts
    "memory": """User preferences:
    - Industry: E-commerce retail
    - Region focus: North America and Europe
    - Preferred data formats: CSV, JSON, interactive dashboards
    - Communication style: Technical but accessible
    - Business context: B2C fashion retailer with online and physical stores
    
    Key facts:
    - Company has 500+ SKUs across clothing, accessories, and footwear
    - Peak sales periods: Black Friday, holiday season, back-to-school
    - Target demographic: 25-45 age group, middle to upper-middle income""",
    
    # RAG: Retrieved relevant documents and data
    "rag": """[Document 1] "Q4 2023 Retail Sales Analysis" - Industry report showing 12% YoY growth in e-commerce, 
    with fashion retail leading at 18% growth. Mobile commerce accounted for 67% of online sales.
    
    [Document 2] "Customer Behavior Trends 2023" - Study indicating 73% of customers research online before purchasing, 
    social media influences 45% of purchase decisions, sustainability concerns affect 62% of buying choices.
    
    [Data Source] Sales dataset: 50,000 transactions, 500+ products, 12-month period with daily granularity""",
    
    # FEWSHOT: Example interactions for pattern matching
    "fewshot": """Example 1:
    Q: "Analyze our Q3 performance and identify key trends"
    A: I'll analyze your Q3 data focusing on revenue trends, product performance, and customer behavior patterns. 
    Let me start by examining the sales metrics and seasonal variations...
    
    Example 2:
    Q: "Create a forecast for next quarter"
    A: I'll generate a sales forecast using your historical data, accounting for seasonality, trends, and external factors. 
    The forecast will include confidence intervals and key assumptions...""",
    
    # SCRATCHPAD: Working memory and intermediate calculations
    "scratchpad": """Current analysis progress:
    1. ✓ Data loaded and validated (50K records, 0.2% missing values)
    2. ✓ Basic statistics calculated (mean, median, std dev)
    3. 🔄 Seasonal decomposition in progress
    4. ⏳ Customer segmentation pending
    5. ⏳ Forecast model training pending
    
    Key observations so far:
    - Revenue shows clear seasonal patterns
    - Weekend sales 40% higher than weekdays
    - Top 20% products generate 75% of revenue"""
}

# Content scores for relevance weighting
content_scores = {
    "system": 1.0,      # Critical - defines assistant behavior
    "task": 0.95,       # High - current user objective
    "history": 0.7,     # Medium - useful context
    "tools": 0.8,       # High - enables functionality
    "memory": 0.75,     # Medium-High - personalization
    "rag": 0.85,        # High - external knowledge
    "fewshot": 0.6,     # Medium - examples for guidance
    "scratchpad": 0.5   # Low - working memory
}
```

### Section Type Descriptions

| Section | Purpose | Content Type | Compression Strategy |
|---------|---------|--------------|---------------------|
| **system** | Core instructions and behavioral constraints | Role definitions, safety guidelines, output format requirements | Sticky (never dropped), minimal compression |
| **task** | Current user request and objectives | Questions, commands, analysis requests, specific requirements | Sticky (high priority), task-focused |
| **history** | Previous conversation context | Past interactions, established facts, user feedback | Task summary compression for long conversations |
| **tools** | Available functions and capabilities | Function signatures, API documentation, usage examples | Signature-only compression for code/tools |
| **memory** | Persistent user preferences and facts | User profile, preferences, recurring patterns | Selective inclusion based on relevance |
| **rag** | External retrieved information | Documents, data sources, research findings | Extractive compression with relevance ranking |
| **fewshot** | Example interactions | Q&A pairs, demonstration examples | Truncate or remove if space limited |
| **scratchpad** | Working memory and calculations | Intermediate results, reasoning steps | Tail placement, first to compress/drop |

### Content Score Guidelines

- **1.0**: Critical information (system instructions, safety constraints)
- **0.8-0.95**: High importance (current task, essential tools, key data)
- **0.6-0.8**: Medium importance (relevant history, useful context)
- **0.3-0.6**: Low importance (examples, supplementary info)
- **0.0-0.3**: Optional information (scratchpad, non-essential examples)

### Compression Strategy Selection

Choose compression methods based on content type:

- **`signature_only`**: For tools/APIs - keeps function signatures
- **`task_summary`**: For conversations - extracts key points
- **`extractive`**: For documents - pulls key sentences
- **`abstractive`**: For long texts - generates summaries
- **`truncate`**: For simple content - basic length reduction

### Best Practices

1. **Keep system instructions concise but comprehensive**
2. **Make task descriptions specific and actionable**
3. **Include relevant context in history, not just chronology**
4. **Structure tool documentation for easy parsing**
5. **Focus memory on actionable preferences, not biographical data**
6. **Curate RAG content for relevance and credibility**
7. **Use fewshot examples that represent desired interaction patterns**
8. **Keep scratchpad focused on current task progress**

## Architecture

The package implements the token budgeting algorithm from the ContextEngineer specification:

1. **8-Bucket System**: Context is divided into semantic buckets (System, Task, Tools, History, Memory, RAG, Few-shot, Scratchpad)
2. **Token Budgeting**: Proportional allocation with minimum/maximum constraints
3. **Dynamic Optimization**: ROI-based allocation using content relevance scores
4. **Position Strategy**: Head/Middle/Tail placement to avoid "Lost in the Middle"

## Core Components

### TokenizerService
Unified tokenization supporting multiple backends (simple regex-based, tiktoken).

### BudgetManager
Token allocation across context buckets with fallback strategies.

### ContextAssembler
Position-aware context assembly with compression support.

### Compressor
Multiple compression strategies: truncate, extractive, abstractive, signature-only.

### PolicyEngine
Task-specific optimization policies (research, code generation, conversation, etc.).

## Configuration

The package supports YAML/JSON configuration files:

```yaml
model:
  name: gpt-4
  context_limit: 8192
  output_target: 1200
  output_headroom: 300

buckets:
  system:
    min_tokens: 300
    max_tokens: 800
    weight: 2.0
    sticky: true
  task:
    min_tokens: 300
    max_tokens: 1500
    weight: 2.5
    sticky: true

policies:
  default:
    drop_order: [fewshot, rag, history, tools]
    placement:
      head: [system, task, tools]
      middle: [rag, history]
      tail: [scratchpad]
```

## Testing

Run tests with pytest:

```bash
pytest tests/
```

## License

MIT License - see LICENSE file for details.
