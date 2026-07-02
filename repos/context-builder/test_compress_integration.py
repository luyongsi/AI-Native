#!/usr/bin/env python
"""Integration test for COMPRESS stage implementation."""

import sys
import os

# Add current directory to path
sys.path.insert(0, os.path.dirname(__file__))

def test_imports():
    """Test all imports work correctly."""
    print("Testing imports...")
    try:
        from compressors.llm_compressor import LLMCompressor
        print("✓ LLMCompressor imported")
    except Exception as e:
        print(f"✗ LLMCompressor import failed: {e}")
        return False

    try:
        from compressors.code_compressor import CodeCompressor
        print("✓ CodeCompressor imported")
    except Exception as e:
        print(f"✗ CodeCompressor import failed: {e}")
        return False

    try:
        from compressors.deduplication import Deduplicator, count_tokens
        print("✓ Deduplication imported")
    except Exception as e:
        print(f"✗ Deduplication import failed: {e}")
        return False

    try:
        from compressors.metrics import CompressionMetrics
        print("✓ CompressionMetrics imported")
    except Exception as e:
        print(f"✗ CompressionMetrics import failed: {e}")
        return False

    try:
        from context_compressor import ContextCompressorV2
        print("✓ ContextCompressorV2 imported")
    except Exception as e:
        print(f"✗ ContextCompressorV2 import failed: {e}")
        return False

    return True


def test_token_counter():
    """Test token counting."""
    print("\nTesting token counter...")
    from compressors.deduplication import count_tokens

    # Test empty
    assert count_tokens('') == 0, "Empty text should return 0"
    print("✓ Empty text: 0 tokens")

    # Test estimation
    text = 'a' * 400
    tokens = count_tokens(text)
    assert tokens == 100, f"400 chars should be ~100 tokens, got {tokens}"
    print("✓ Token estimation: 400 chars = 100 tokens")

    return True


def test_code_compressor():
    """Test code compressor."""
    print("\nTesting code compressor...")
    from compressors.code_compressor import CodeCompressor

    compressor = CodeCompressor()

    # Test Python comment removal
    code = '''def hello():
    # This is a comment
    print("Hello")
    return True'''

    compressed = compressor.compress(code, 'python')
    assert '# This is a comment' not in compressed, "Comments should be removed"
    assert 'print' in compressed, "Code should be preserved"
    print("✓ Python comment removal works")

    # Test print statement removal
    assert 'print' not in compressed, "Print statements should be removed"
    print("✓ Print statement removal works")

    # Test empty code
    assert compressor.compress('', 'python') == '', "Empty code should return empty"
    print("✓ Empty code handling works")

    # Test compression ratio
    ratio = CodeCompressor.estimate_compression_ratio(code, 'python')
    assert 0 < ratio < 1, f"Ratio should be between 0 and 1, got {ratio}"
    print(f"✓ Compression ratio: {ratio:.2%}")

    return True


def test_deduplication():
    """Test deduplication."""
    print("\nTesting deduplication...")
    from compressors.deduplication import (
        jaccard_similarity,
        sequence_similarity,
        Deduplicator,
    )

    # Test Jaccard similarity
    text = 'the quick brown fox'
    sim = jaccard_similarity(text, text)
    assert sim == 1.0, "Identical texts should have 100% similarity"
    print("✓ Jaccard similarity: identical = 1.0")

    # Test sequence similarity
    text1 = 'the quick brown fox jumps'
    text2 = 'the quick brown fox'
    sim = sequence_similarity(text1, text2)
    assert sim > 0.7, "Similar texts should have high similarity"
    print(f"✓ Sequence similarity: {sim:.2%}")

    # Test deduplicator
    dedup = Deduplicator(similarity_threshold=0.90)
    candidates = [
        {'content': 'identical content', 'relevance': 0.5},
        {'content': 'identical content', 'relevance': 0.6},
    ]
    result = dedup.deduplicate(candidates)
    assert len(result) == 1, f"Should deduplicate to 1, got {len(result)}"
    assert result[0]['relevance'] == 0.6, "Should keep higher relevance"
    print("✓ Deduplication keeps highest relevance")

    return True


def test_llm_compressor():
    """Test LLM compressor."""
    print("\nTesting LLM compressor...")
    from compressors.llm_compressor import LLMCompressor

    compressor = LLMCompressor(use_mock=True)

    # Test mock compression
    text = 'word ' * 200  # 1000 chars
    result = compressor._mock_compress(text, target_ratio=0.5)
    assert len(result) < len(text), "Compressed should be shorter"
    assert len(result) > len(text) * 0.3, "Should not compress too aggressively"
    print(f"✓ Mock compression: {len(text)} -> {len(result)} chars ({len(result)/len(text):.2%})")

    return True


def test_metrics():
    """Test metrics collection."""
    print("\nTesting metrics...")
    from compressors.metrics import CompressionMetrics

    metrics = CompressionMetrics()

    # Record compression
    metrics.record_compression(1000, 500, 100.0, 'code')
    assert abs(metrics.compress_ratio - 0.5) < 0.01, "Ratio should be ~0.5"
    print(f"✓ Compression metric: ratio = {metrics.compress_ratio:.2%}")

    # Record deduplication
    metrics.record_deduplication(100, 80)
    assert metrics.dedup_removed_count == 20, "Should track deduped count"
    print("✓ Deduplication metric recorded")

    # Check metrics dict
    metrics_dict = metrics.to_dict()
    assert 'context_builder_compress_ratio' in metrics_dict, "Metrics dict missing keys"
    assert 'context_builder_compress_code_total' in metrics_dict, "Metrics dict missing keys"
    print("✓ Metrics dictionary complete")

    return True


def test_context_compressor_v2():
    """Test advanced context compressor."""
    print("\nTesting ContextCompressorV2...")
    from context_compressor import ContextCompressorV2

    compressor = ContextCompressorV2(use_mock_llm=True)

    # Test language detection
    assert compressor._get_language('file.py') == 'python'
    assert compressor._get_language('file.js') == 'javascript'
    assert compressor._get_language(None) == 'python'
    print("✓ Language detection works")

    # Test compress candidates
    candidates = [
        {
            'content': 'print("test")  # comment',
            'type': 'code',
            'file': 'test.py',
            'content_type': 'code',
            'relevance': 0.9,
        }
    ]
    result, metrics = compressor.compress_candidates(candidates)
    assert len(result) > 0, "Should return compressed candidates"
    assert 'token_count' in result[0], "Should have token_count"
    print("✓ Compress candidates works")

    # Check metrics
    assert metrics['context_builder_compress_code_total'] > 0, "Should record code compression"
    print("✓ Metrics recorded correctly")

    return True


def main():
    """Run all integration tests."""
    print("=" * 60)
    print("COMPRESS Stage Integration Tests")
    print("=" * 60)

    tests = [
        test_imports,
        test_token_counter,
        test_code_compressor,
        test_deduplication,
        test_llm_compressor,
        test_metrics,
        test_context_compressor_v2,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            if test():
                passed += 1
            else:
                failed += 1
                print(f"✗ {test.__name__} failed")
        except Exception as e:
            failed += 1
            print(f"✗ {test.__name__} error: {e}")
            import traceback
            traceback.print_exc()

    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)

    return failed == 0


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
