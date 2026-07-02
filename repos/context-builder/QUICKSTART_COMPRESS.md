# COMPRESS Stage - Quick Start Guide

## 5-Minute Quick Start

### 1. Import the Compressor

```python
from context_compressor import ContextCompressorV2

# Create compressor (use mock for testing)
compressor = ContextCompressorV2(use_mock_llm=True)
```

### 2. Compress Your Candidates

```python
candidates = [
    {
        'content': '''
def process_data(items):
    # Validate input
    if not items:
        print("Warning: empty list")
        return []
    
    logger.info("Processing...")
    result = [x * 2 for x in items]
    print(f"Result: {result}")
    return result
''',
        'type': 'code',
        'file': 'utils.py',
        'content_type': 'code',
        'relevance': 0.95,
    }
]

# Compress
compressed, metrics = compressor.compress_candidates(candidates)

print(f"Compressed {len(candidates)} items")
print(f"Ratio: {metrics['context_builder_compress_ratio']:.1%}")
```

### 3. Check Metrics

```python
metrics = compressor.get_metrics()

print(f"Code compressions: {metrics['context_builder_compress_code_total']}")
print(f"Duration: {metrics['context_builder_compress_duration_ms']:.1f}ms")
print(f"Duplicates removed: {metrics['context_builder_compress_dedup_removed_total']}")
```

---

## Common Tasks

### Task 1: Compress Code Files

```python
from compressors.code_compressor import CodeCompressor

compressor = CodeCompressor()

# Python
python_code = "def foo():\n    # comment\n    print('test')\n    return True"
result = compressor.compress(python_code, 'python')

# JavaScript
js_code = "function foo() { console.log('test'); return true; }"
result = compressor.compress(js_code, 'javascript')

# Any language
result = compressor.compress(code, 'go')  # or 'rust', 'java', etc.
```

### Task 2: Deduplicate Candidates

```python
from compressors.deduplication import Deduplicator

dedup = Deduplicator(similarity_threshold=0.90)

candidates = [
    {'content': 'def process(x): return x * 2', 'relevance': 0.8},
    {'content': 'def process(x): return x * 2', 'relevance': 0.9},  # Duplicate
    {'content': 'def filter(x): return x > 0', 'relevance': 0.7},
]

# Dedup (keeps highest relevance)
result = dedup.deduplicate(candidates)
# Result: 2 items (similar items merged)
```

### Task 3: Count Tokens

```python
from compressors.deduplication import count_tokens

text = "hello world how are you"
tokens = count_tokens(text)  # ~6 tokens
```

### Task 4: Calculate Similarity

```python
from compressors.deduplication import jaccard_similarity, sequence_similarity

text1 = "the quick brown fox"
text2 = "the quick brown fox jumps"

# Word-level similarity
jac = jaccard_similarity(text1, text2)  # ~0.75

# Sequence-level similarity
seq = sequence_similarity(text1, text2)  # ~0.95

# Hybrid
from compressors.deduplication import calculate_similarity
hybrid = calculate_similarity(text1, text2, method='hybrid')  # ~0.85
```

### Task 5: Get Compression Metrics

```python
from compressors.metrics import CompressionMetrics

metrics = CompressionMetrics()

# Record some operations
metrics.record_compression(1000, 500, 100.0, 'code')
metrics.record_deduplication(100, 85)

# Get dict
data = metrics.to_dict()

print(f"Ratio: {data['context_builder_compress_ratio']:.1%}")
print(f"Dedup removed: {data['context_builder_compress_dedup_removed_total']}")
print(f"Duration P95: {data['context_builder_compress_duration_p95_ms']:.1f}ms")
```

---

## Configuration

### Mock vs Real LLM

```python
# Mock (for testing - fast)
from context_compressor import ContextCompressorV2
compressor = ContextCompressorV2(use_mock_llm=True)

# Real (requires DeepSeek API key)
import os
api_key = os.getenv('DEEPSEEK_API_KEY')
compressor = ContextCompressorV2(
    llm_api_key=api_key,
    use_mock_llm=False
)
```

### Adjust Deduplication Threshold

```python
from context_compressor import ContextCompressorV2

# Stricter dedup (remove more duplicates)
compressor = ContextCompressorV2(similarity_threshold=0.95)

# Lenient dedup (keep more candidates)
compressor = ContextCompressorV2(similarity_threshold=0.80)
```

### Adjust Compression Ratio

```python
candidates = [...]

# Compress to 40% (aggressive)
compressed, metrics = compressor.compress_candidates(candidates, target_compression_ratio=0.4)

# Compress to 70% (conservative)
compressed, metrics = compressor.compress_candidates(candidates, target_compression_ratio=0.7)
```

---

## Examples with Output

### Example 1: Code Compression

**Input**:
```python
def calculate(numbers):
    """Calculate statistics."""
    # Debug logging
    print("Starting calculation")
    logger.debug(f"Numbers: {numbers}")
    
    # Validate
    if not numbers:
        print("Empty list!")
        return None
    
    # Process
    result = sum(numbers) / len(numbers)
    print(f"Result: {result}")
    
    return result
```

**Output** (after compression):
```python
def calculate(numbers):
    """Calculate statistics."""
    if not numbers:
        return None
    result = sum(numbers) / len(numbers)
    return result
```

**Ratio**: 52% (reduction: 48%)

---

### Example 2: Deduplication

**Input** (3 candidates):
```
1. content: "function process(data) { ... }" 
   relevance: 0.75

2. content: "function process(data) { ... }" 
   relevance: 0.85

3. content: "function filter(data) { ... }"
   relevance: 0.70
```

**Output** (2 candidates):
```
1. content: "function process(data) { ... }"
   relevance: 0.85  (merged, kept highest)

2. content: "function filter(data) { ... }"
   relevance: 0.70  (different, kept)
```

**Duplicates removed**: 1

---

### Example 3: Full Pipeline

```python
from context_compressor import ContextCompressorV2

# Initialize
compressor = ContextCompressorV2(use_mock_llm=True)

# Sample candidates
candidates = [
    {
        'content': 'def foo(): print("test"); return True',
        'type': 'code',
        'file': 'test.py',
        'relevance': 0.95,
    },
    {
        'content': 'Long documentation text about the feature...' * 5,
        'type': 'knowledge',
        'relevance': 0.80,
    },
]

# Compress
result, metrics = compressor.compress_candidates(candidates)

# Output
print(f"Items: {len(candidates)} → {len(result)}")
print(f"Compression ratio: {metrics['context_builder_compress_ratio']:.1%}")
print(f"Code compressions: {metrics['context_builder_compress_code_total']}")
print(f"Duration: {metrics['context_builder_compress_duration_ms']:.1f}ms")
```

**Output**:
```
Items: 2 → 2
Compression ratio: 55.2%
Code compressions: 1
Duration: 125.3ms
```

---

## Troubleshooting

### Q: "ImportError: No module named compressors"

**A**: Make sure you're in the context-builder directory:
```bash
cd /d/Vibe\ Coding/AI\ Agent/repos/context-builder
python your_script.py
```

### Q: "Compression not happening?"

**A**: Check that items have content:
```python
assert len(candidates) > 0
assert all('content' in c for c in candidates)
```

### Q: "Slow compression?"

**A**: 
- Use mock LLM instead of API
- Increase similarity_threshold (fewer comparisons)
- Process in smaller batches

### Q: "Lost too much information?"

**A**:
- Increase target_compression_ratio (e.g., 0.7)
- Reduce similarity_threshold
- Don't compress head/tail items

---

## Performance Tips

### Tip 1: Batch Processing
```python
# Good: Process in batches
batches = [candidates[i:i+50] for i in range(0, len(candidates), 50)]
for batch in batches:
    compressed, metrics = compressor.compress_candidates(batch)
```

### Tip 2: Use Mock LLM for Testing
```python
# Fast (mock): ~100ms
compressor = ContextCompressorV2(use_mock_llm=True)

# Slow (API): ~500-2000ms
compressor = ContextCompressorV2(llm_api_key='...', use_mock_llm=False)
```

### Tip 3: Reuse Compressor Instance
```python
# Good: Create once
compressor = ContextCompressorV2(use_mock_llm=True)
for candidates in candidate_batches:
    result, metrics = compressor.compress_candidates(candidates)

# Bad: Create for each batch
for candidates in candidate_batches:
    compressor = ContextCompressorV2(use_mock_llm=True)  # Wasteful
    result, metrics = compressor.compress_candidates(candidates)
```

### Tip 4: Monitor Metrics
```python
# Always check metrics
result, metrics = compressor.compress_candidates(candidates)

if metrics['context_builder_compress_duration_ms'] > 1000:
    logger.warning(f"Slow compression: {metrics['context_builder_compress_duration_ms']:.1f}ms")

if metrics['context_builder_compress_ratio'] < 0.4:
    logger.info(f"Aggressive compression: {metrics['context_builder_compress_ratio']:.1%}")
```

---

## Next Steps

1. **Read** `COMPRESS_IMPLEMENTATION.md` for detailed documentation
2. **Run** `python validate_compress.py` to see it in action
3. **Test** `python test_compress_integration.py` to verify everything works
4. **Integrate** into your Context Builder pipeline

---

## Supported Languages

```
Python, JavaScript, TypeScript, JSX, TSX, Go, Rust, Java,
C, C++, C#, Ruby, PHP, Shell, Bash, SQL, and more
```

Auto-detection from file extension. Custom language support by adding patterns.

---

## API Reference

### ContextCompressorV2

```python
compressor = ContextCompressorV2(
    llm_api_key=None,
    use_mock_llm=True,
    similarity_threshold=0.90
)

# Main methods
compress_candidates(candidates, target_compression_ratio=0.5)
compress_candidates_async(candidates, target_compression_ratio=0.5)
get_metrics()
reset_metrics()
```

### CodeCompressor

```python
compressor = CodeCompressor()

compress(code, language='python')
estimate_compression_ratio(code, language)
```

### Deduplicator

```python
dedup = Deduplicator(similarity_threshold=0.90)

deduplicate(candidates, similarity_method='hybrid')
get_dedup_stats()
```

### CompressionMetrics

```python
metrics = CompressionMetrics()

record_compression(original_tokens, compressed_tokens, duration_ms, compress_type)
record_deduplication(original_count, deduped_count)
record_error(error)
to_dict()
reset()
```

---

For more details, see `COMPRESS_IMPLEMENTATION.md`
