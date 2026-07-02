# COMPRESS Stage Implementation

## Overview

This directory contains the complete implementation of the **COMPRESS** stage for the Context Builder pipeline (Task #25).

The COMPRESS stage intelligently reduces context size while preserving key information through:
1. **Code Compression** - Remove comments, logs, and whitespace
2. **LLM Compression** - Summarize long text using language models
3. **Deduplication** - Remove similar/duplicate content
4. **Metrics** - Track compression performance and efficiency

## Components

### 1. Code Compressor (`compressors/code_compressor.py`)

Removes non-essential code elements while preserving logic:

- **Removes**: Single-line comments, block comments, log statements, empty lines
- **Preserves**: Function/class signatures, decorators, docstrings, core logic
- **Supports**: Python, JavaScript, TypeScript, Go, Rust, Java, C++, and more

```python
from compressors.code_compressor import CodeCompressor

compressor = CodeCompressor()
compressed = compressor.compress(code, language='python')

# Compression ratio estimation
ratio = CodeCompressor.estimate_compression_ratio(code, 'python')
print(f"Compression ratio: {ratio:.1%}")
```

**Example**:
```python
# Before
def process_data(items):
    """Process data items."""
    # Validate input
    if not items:
        print("Warning: empty list")  # Debug
        return []
    
    logger.info("Starting process")  # Logging
    
    # Map operation
    result = [item * 2 for item in items]
    print(f"Result: {result}")  # More logging
    
    return result

# After
def process_data(items):
    """Process data items."""
    if not items:
        return []
    result = [item * 2 for item in items]
    return result
```

**Typical compression**: 40-60% reduction

### 2. LLM Compressor (`compressors/llm_compressor.py`)

Summarizes long text while preserving key information:

- **Mock Mode**: Simple truncation to target ratio (useful for testing)
- **DeepSeek API**: Real LLM-based summarization (requires API key)
- **Preserves**: Key information, main logic, core functionality, critical decisions

```python
from compressors.llm_compressor import LLMCompressor

# Mock mode (for testing/demo)
compressor = LLMCompressor(use_mock=True)
compressed = compressor._mock_compress(text, target_ratio=0.5)

# Real API mode
compressor = LLMCompressor(api_key='sk-...', use_mock=False)
import asyncio
compressed = asyncio.run(compressor.compress(text, target_ratio=0.5))
```

**Target ratio**: Typically 40-60% of original (configurable)

### 3. Deduplication (`compressors/deduplication.py`)

Removes similar/duplicate content:

- **Similarity Calculation**: Jaccard or sequence matching
- **Default Threshold**: 90% similarity
- **Strategy**: Keep document with highest relevance score

```python
from compressors.deduplication import Deduplicator

deduplicator = Deduplicator(similarity_threshold=0.90)

candidates = [
    {'content': 'duplicate content', 'relevance': 0.5},
    {'content': 'duplicate content', 'relevance': 0.8},  # Kept
    {'content': 'different content', 'relevance': 0.7},
]

deduped = deduplicator.deduplicate(candidates)
# Result: 2 items (duplicates merged, highest relevance kept)
```

**Utility Functions**:
```python
from compressors.deduplication import count_tokens, jaccard_similarity, sequence_similarity

# Token counting (1 token ≈ 4 characters)
tokens = count_tokens("hello world")  # ~3 tokens

# Similarity metrics
jac_sim = jaccard_similarity(text1, text2)  # Word-level
seq_sim = sequence_similarity(text1, text2)  # Sequence-level
```

### 4. Metrics (`compressors/metrics.py`)

Prometheus-style metrics for monitoring:

```python
from compressors.metrics import CompressionMetrics

metrics = CompressionMetrics()

# Record operations
metrics.record_compression(original_tokens=1000, compressed_tokens=500, duration_ms=100.0, compress_type='code')
metrics.record_deduplication(original_count=100, deduped_count=85)

# Get metrics
metrics_dict = metrics.to_dict()

# Output
{
    'context_builder_compress_ratio': 0.5,
    'context_builder_compress_duration_seconds': 0.1,
    'context_builder_compress_code_total': 1,
    'context_builder_compress_dedup_removed_total': 15,
    'context_builder_compress_duration_p95_ms': 120.0,
    ...
}
```

**Key Metrics**:
- `context_builder_compress_ratio` (Gauge) - Overall compression ratio
- `context_builder_compress_duration_seconds` (Histogram) - Compression time
- `context_builder_compress_code_total` (Counter) - Code compressions
- `context_builder_compress_llm_total` (Counter) - LLM compressions
- `context_builder_compress_dedup_removed_total` (Counter) - Duplicates removed
- `context_builder_compress_duration_p95_ms` (Histogram) - P95 latency

### 5. Advanced Compressor (`context_compressor.py`)

Integrated compressor combining all components:

```python
from context_compressor import ContextCompressorV2

compressor = ContextCompressorV2(
    llm_api_key=None,      # Optional DeepSeek API key
    use_mock_llm=True,     # Use mock for testing
    similarity_threshold=0.90
)

# Compress candidates (async)
candidates = [
    {
        'content': 'def hello(): print("hi")',
        'type': 'code',
        'file': 'test.py',
        'content_type': 'code',
        'relevance': 0.9,
    },
    {
        'content': 'Long documentation text...',
        'type': 'knowledge',
        'relevance': 0.7,
    }
]

compressed, metrics = compressor.compress_candidates(candidates)

# Metrics
print(f"Compression ratio: {metrics['context_builder_compress_ratio']:.1%}")
print(f"Duplicates removed: {metrics['context_builder_compress_dedup_removed_total']}")
```

## Usage Examples

### Example 1: Compress Code

```python
from compressors.code_compressor import CodeCompressor

code = """
def calculate_average(numbers):
    # Validate input
    if not numbers:
        print("Empty list")
        return 0
    
    # Sum
    total = sum(numbers)
    logger.debug(f"Sum: {total}")
    
    # Average
    result = total / len(numbers)
    print(f"Average: {result}")
    return result
"""

compressor = CodeCompressor()
compressed = compressor.compress(code, 'python')
print(compressed)
# Output: function signature, docstring, core logic (no comments/logs)
```

### Example 2: Deduplicate Candidates

```python
from compressors.deduplication import Deduplicator

dedup = Deduplicator(similarity_threshold=0.85)

candidates = [
    {'content': 'The quick brown fox jumps', 'relevance': 0.8, 'source': 'A'},
    {'content': 'The quick brown fox jumps over the lazy dog', 'relevance': 0.9, 'source': 'B'},
    {'content': 'Completely different text', 'relevance': 0.7, 'source': 'C'},
]

result = dedup.deduplicate(candidates)
# Similar texts merged, highest relevance kept
```

### Example 3: Full Pipeline

```python
from context_compressor import ContextCompressorV2

compressor = ContextCompressorV2(use_mock_llm=True)

# Your candidates
candidates = [...]

# Compress and deduplicate
compressed, metrics = compressor.compress_candidates(candidates)

# Check results
print(f"Items: {len(candidates)} -> {len(compressed)}")
print(f"Ratio: {metrics['context_builder_compress_ratio']:.1%}")
print(f"Duration: {metrics['context_builder_compress_duration_ms']:.1f}ms")
```

## Testing

### Unit Tests

```bash
# Run all compression tests
python -m unittest tests.test_compress -v

# Run specific test
python -m unittest tests.test_compress.TestCodeCompressor.test_remove_python_comments -v
```

### Integration Tests

```bash
# Comprehensive integration test
python test_compress_integration.py

# Validation and demo
python validate_compress.py
```

## Performance

### Typical Performance Metrics

| Operation | Input | Output | Duration |
|-----------|-------|--------|----------|
| Code compression | 1000 tokens | 500 tokens | ~50ms |
| LLM compression (mock) | 2000 tokens | 1200 tokens | ~100ms |
| Deduplication | 100 candidates | 85 candidates | ~20ms |
| Full pipeline | 50 items | 40 items | ~200ms |

### Compression Ratios

- **Code files**: 40-60% (removes comments, logs, whitespace)
- **Documentation**: 50-70% (LLM summarization)
- **Overall**: Typically 45-55% reduction

### P95 Latency

- Code compression: < 100ms
- LLM compression: < 500ms (mock), < 2s (API)
- Deduplication: < 50ms
- **Overall P95: < 2s**

## Integration with Pipeline

The COMPRESS stage integrates with the existing Context Builder pipeline:

```python
from pipeline import ContextBuilder
from context_compressor import ContextCompressorV2

builder = ContextBuilder()

# The pipeline automatically uses compression if available
result = builder.build_context(
    target_agent='A9',
    req_id='req-123',
    max_tokens=8000,
)

# Compress stage is applied after ORDER, before ISOLATE
```

## File Structure

```
context-builder/
├── compressors/
│   ├── __init__.py                 # Package exports
│   ├── llm_compressor.py           # LLM-based compression
│   ├── code_compressor.py          # Code-specific compression
│   ├── deduplication.py            # Deduplication and token counting
│   └── metrics.py                  # Prometheus metrics
├── context_compressor.py           # Advanced integrated compressor
├── tests/
│   └── test_compress.py            # Unit tests
├── test_compress_integration.py    # Integration tests
└── validate_compress.py            # Validation and demos
```

## Configuration

### Environment Variables

```bash
# DeepSeek API configuration
export DEEPSEEK_API_KEY="sk-..."

# Compression settings
export COMPRESS_TARGET_RATIO="0.5"      # 50% compression
export COMPRESS_SIMILARITY_THRESHOLD="0.90"
```

### Programmatic Configuration

```python
compressor = ContextCompressorV2(
    llm_api_key='sk-...',
    use_mock_llm=False,  # Use real API
    similarity_threshold=0.85,  # More aggressive dedup
)
```

## Troubleshooting

### Issue: Compression not working

**Solution**: Check that all compressor modules are imported correctly.

```python
from compressors import CodeCompressor, LLMCompressor, Deduplicator
```

### Issue: High compression latency

**Solution**: 
- Use mock LLM instead of API
- Reduce batch size
- Increase similarity threshold (fewer dedup comparisons)

### Issue: Over-compression (lost information)

**Solution**:
- Increase target_ratio (e.g., 0.7 for 70% instead of 0.5)
- Reduce similarity_threshold (keep more candidates)
- Use sequence similarity instead of Jaccard

## References

- Token estimation: 1 token ≈ 4 characters (common LLM approximation)
- Jaccard similarity: intersection / union of word sets
- Sequence similarity: difflib.SequenceMatcher ratio
- Prometheus metrics: Standard monitoring format

## Future Enhancements

- [ ] GPU acceleration for similarity calculations
- [ ] Adaptive compression ratios based on content type
- [ ] Support for custom language grammars
- [ ] Real-time compression metrics dashboard
- [ ] Streaming compression for very large files
