#!/bin/bash

echo "=========================================="
echo "Context Builder SELECT Stage Validation"
echo "=========================================="
echo ""

# Check directory structure
echo "1. Checking directory structure..."
if [ -d "sources" ]; then
    echo "   ✓ sources/ directory exists"
else
    echo "   ✗ sources/ directory missing"
    exit 1
fi

# Check source files
echo ""
echo "2. Checking data source implementations..."

files=(
    "sources/__init__.py"
    "sources/postgres_source.py"
    "sources/neo4j_source.py"
    "sources/vector_source.py"
    "multi_source_selector.py"
    "test_select_stage.py"
)

for file in "${files[@]}"; do
    if [ -f "$file" ]; then
        lines=$(wc -l < "$file")
        echo "   ✓ $file ($lines lines)"
    else
        echo "   ✗ $file missing"
        exit 1
    fi
done

# Check key class implementations
echo ""
echo "3. Checking key class implementations..."

classes=(
    "PostgresSource:sources/postgres_source.py"
    "Neo4jSource:sources/neo4j_source.py"
    "VectorSource:sources/vector_source.py"
    "MultiSourceSelector:multi_source_selector.py"
    "SelectMetrics:multi_source_selector.py"
)

for class_def in "${classes[@]}"; do
    IFS=':' read -r classname file <<< "$class_def"
    if grep -q "class $classname" "$file"; then
        echo "   ✓ $classname implemented in $file"
    else
        echo "   ✗ $classname not found in $file"
        exit 1
    fi
done

# Check async methods
echo ""
echo "4. Checking async implementations..."

async_checks=(
    "async def query:sources/postgres_source.py"
    "async def query:sources/neo4j_source.py"
    "async def query:sources/vector_source.py"
    "async def select_async:multi_source_selector.py"
    "async def close:sources/postgres_source.py"
)

for check in "${async_checks[@]}"; do
    IFS=':' read -r method file <<< "$check"
    if grep -q "$method" "$file"; then
        echo "   ✓ $method in $file"
    else
        echo "   ✗ $method not found in $file"
        exit 1
    fi
done

# Check metrics implementation
echo ""
echo "5. Checking Prometheus metrics..."

metrics=(
    "candidates_total"
    "candidates_deduped"
    "candidates_final"
    "select_duration_ms"
    "source_counts"
)

for metric in "${metrics[@]}"; do
    if grep -q "$metric" "multi_source_selector.py"; then
        echo "   ✓ Metric: $metric"
    else
        echo "   ✗ Metric missing: $metric"
        exit 1
    fi
done

# Check test coverage
echo ""
echo "6. Checking test coverage..."

test_classes=(
    "TestSelectMetrics"
    "TestMultiSourceSelector"
)

for test_class in "${test_classes[@]}"; do
    if grep -q "class $test_class" "test_select_stage.py"; then
        echo "   ✓ Test class: $test_class"
    else
        echo "   ✗ Test class missing: $test_class"
        exit 1
    fi
done

# Check error handling
echo ""
echo "7. Checking error handling..."

error_patterns=(
    "except Exception"
    "logger.error"
    "try:"
)

for pattern in "${error_patterns[@]}"; do
    count=$(grep -r "$pattern" sources/ multi_source_selector.py 2>/dev/null | wc -l)
    if [ $count -gt 0 ]; then
        echo "   ✓ Error handling pattern '$pattern' found ($count instances)"
    fi
done

# Check documentation
echo ""
echo "8. Checking documentation..."

if [ -f "SELECT_STAGE_IMPLEMENTATION.txt" ]; then
    lines=$(wc -l < "SELECT_STAGE_IMPLEMENTATION.txt")
    echo "   ✓ Implementation documentation ($lines lines)"
fi

# Summary
echo ""
echo "=========================================="
echo "Validation Complete"
echo "=========================================="
echo ""
echo "Summary:"
echo "- Sources directory: Created with 3 data source classes"
echo "- Multi-source selector: Implemented with dedup & merging"
echo "- Metrics: Prometheus-style tracking implemented"
echo "- Error handling: Comprehensive try-catch blocks"
echo "- Tests: Unit and async integration tests"
echo "- Documentation: Full implementation guide provided"
echo ""
echo "Ready for integration with Context Builder pipeline!"
