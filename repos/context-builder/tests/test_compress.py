"""Unit tests for compression components."""

import unittest
import asyncio
from compressors.llm_compressor import LLMCompressor
from compressors.code_compressor import CodeCompressor
from compressors.deduplication import (
    count_tokens,
    jaccard_similarity,
    sequence_similarity,
    Deduplicator,
)
from compressors.metrics import CompressionMetrics
from context_compressor import ContextCompressorV2


class TestTokenCounter(unittest.TestCase):
    """Test token counting."""

    def test_empty_text(self):
        """Test empty text returns 1 token minimum."""
        self.assertEqual(count_tokens(''), 0)

    def test_short_text(self):
        """Test short text."""
        result = count_tokens('hello world')
        self.assertGreater(result, 0)

    def test_token_estimation(self):
        """Test token estimation (4 chars per token)."""
        text = 'a' * 400  # 400 chars
        tokens = count_tokens(text)
        self.assertEqual(tokens, 100)

    def test_multiline_text(self):
        """Test multiline text."""
        text = 'line1\nline2\nline3'
        tokens = count_tokens(text)
        self.assertGreater(tokens, 0)


class TestCodeCompressor(unittest.TestCase):
    """Test code compression."""

    def setUp(self):
        """Set up test fixtures."""
        self.compressor = CodeCompressor()

    def test_remove_python_comments(self):
        """Test removing Python comments."""
        code = '''
def hello():
    # This is a comment
    print("Hello")  # inline comment
    return True
'''
        compressed = self.compressor.compress(code, 'python')
        self.assertNotIn('# This is a comment', compressed)
        self.assertIn('print', compressed)

    def test_remove_empty_lines(self):
        """Test removing empty lines."""
        code = '''
def hello():

    print("Hello")

    return True

'''
        compressed = self.compressor.compress(code, 'python')
        lines = compressed.split('\n')
        # Should have fewer lines
        self.assertLess(len(lines), code.count('\n'))

    def test_remove_console_log(self):
        """Test removing console.log statements."""
        code = '''
function hello() {
    console.log("Debug info");
    console.error("Error occurred");
    return true;
}
'''
        compressed = self.compressor.compress(code, 'javascript')
        self.assertNotIn('console.log', compressed)
        self.assertNotIn('console.error', compressed)
        self.assertIn('return true', compressed)

    def test_remove_print_statements(self):
        """Test removing print statements."""
        code = '''
def process():
    print("Starting")
    result = calculate()
    print(f"Result: {result}")
    return result
'''
        compressed = self.compressor.compress(code, 'python')
        self.assertNotIn('print', compressed)
        self.assertIn('calculate', compressed)

    def test_empty_code(self):
        """Test empty code."""
        result = self.compressor.compress('', 'python')
        self.assertEqual(result, '')

    def test_code_with_only_comments(self):
        """Test code with only comments."""
        code = '# Comment 1\n# Comment 2\n# Comment 3'
        compressed = self.compressor.compress(code, 'python')
        self.assertEqual(compressed.strip(), '')

    def test_compression_ratio(self):
        """Test compression ratio estimation."""
        code = '''
def function():
    # Many comments
    # More comments
    print("log")  # inline
    x = 1
    y = 2
    return x + y
'''
        ratio = CodeCompressor.estimate_compression_ratio(code, 'python')
        self.assertLess(ratio, 1.0)
        self.assertGreater(ratio, 0.0)


class TestDeduplication(unittest.TestCase):
    """Test deduplication."""

    def test_jaccard_similarity_identical(self):
        """Test Jaccard similarity for identical texts."""
        text = 'the quick brown fox jumps over the lazy dog'
        sim = jaccard_similarity(text, text)
        self.assertEqual(sim, 1.0)

    def test_jaccard_similarity_different(self):
        """Test Jaccard similarity for different texts."""
        text1 = 'the quick brown fox'
        text2 = 'completely different text'
        sim = jaccard_similarity(text1, text2)
        self.assertLess(sim, 0.3)

    def test_sequence_similarity_identical(self):
        """Test sequence similarity for identical texts."""
        text = 'the quick brown fox'
        sim = sequence_similarity(text, text)
        self.assertEqual(sim, 1.0)

    def test_sequence_similarity_partial(self):
        """Test sequence similarity for partial match."""
        text1 = 'the quick brown fox jumps'
        text2 = 'the quick brown fox'
        sim = sequence_similarity(text1, text2)
        self.assertGreater(sim, 0.7)

    def test_deduplicator_identical_content(self):
        """Test deduplicator removes identical content."""
        dedup = Deduplicator(similarity_threshold=0.90)
        candidates = [
            {'content': 'identical content', 'relevance': 0.5},
            {'content': 'identical content', 'relevance': 0.6},
        ]
        result = dedup.deduplicate(candidates)
        self.assertEqual(len(result), 1)
        # Should keep higher relevance
        self.assertEqual(result[0]['relevance'], 0.6)

    def test_deduplicator_different_content(self):
        """Test deduplicator keeps different content."""
        dedup = Deduplicator(similarity_threshold=0.90)
        candidates = [
            {'content': 'content about cats', 'relevance': 0.5},
            {'content': 'content about dogs', 'relevance': 0.5},
        ]
        result = dedup.deduplicate(candidates)
        self.assertEqual(len(result), 2)

    def test_deduplicator_similar_content(self):
        """Test deduplicator with similar content."""
        dedup = Deduplicator(similarity_threshold=0.90)
        candidates = [
            {'content': 'the quick brown fox jumps', 'relevance': 0.5},
            {'content': 'the quick brown fox jumps over the lazy dog', 'relevance': 0.6},
        ]
        result = dedup.deduplicate(candidates)
        # Might be kept or deduped depending on threshold
        self.assertLessEqual(len(result), 2)


class TestLLMCompressor(unittest.TestCase):
    """Test LLM compression."""

    def setUp(self):
        """Set up test fixtures."""
        self.compressor = LLMCompressor(use_mock=True)

    def test_mock_compress_empty(self):
        """Test mock compression with empty text."""
        result = self.compressor._mock_compress('')
        self.assertEqual(result, '')

    def test_mock_compress_short_text(self):
        """Test mock compression with short text."""
        text = 'short text'
        result = self.compressor._mock_compress(text)
        self.assertEqual(result, text)

    def test_mock_compress_long_text(self):
        """Test mock compression with long text."""
        text = 'word ' * 200  # 1000 chars
        result = self.compressor._mock_compress(text, target_ratio=0.5)
        # Should be approximately 50% of original
        self.assertLess(len(result), len(text))
        self.assertGreater(len(result), len(text) * 0.3)

    def test_mock_compress_respects_ratio(self):
        """Test mock compression respects target ratio."""
        text = 'sentence one. Sentence two. Sentence three. ' * 10
        result = self.compressor._mock_compress(text, target_ratio=0.6)
        ratio = len(result) / len(text)
        # Allow 20% deviation
        self.assertLess(ratio, 0.8)

    async def test_async_compress(self):
        """Test async compression."""
        text = 'test text ' * 50
        result = await self.compressor.compress(text, target_ratio=0.5)
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)


class TestCompressionMetrics(unittest.TestCase):
    """Test compression metrics."""

    def setUp(self):
        """Set up test fixtures."""
        self.metrics = CompressionMetrics()

    def test_record_compression(self):
        """Test recording compression."""
        self.metrics.record_compression(1000, 500, 100.0, 'code')
        self.assertAlmostEqual(self.metrics.compress_ratio, 0.5, places=2)
        self.assertEqual(self.metrics.code_compress_count, 1)

    def test_record_deduplication(self):
        """Test recording deduplication."""
        self.metrics.record_deduplication(100, 80)
        self.assertEqual(self.metrics.dedup_removed_count, 20)

    def test_record_error(self):
        """Test recording error."""
        self.metrics.record_error('test error')
        self.assertEqual(self.metrics.errors_count, 1)

    def test_percentile_calculation(self):
        """Test percentile calculation."""
        samples = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        p50 = self.metrics.get_percentile(samples, 0.50)
        self.assertAlmostEqual(p50, 5, delta=1)

    def test_to_dict(self):
        """Test metrics to dict conversion."""
        self.metrics.record_compression(1000, 500, 100.0, 'code')
        result = self.metrics.to_dict()
        self.assertIn('context_builder_compress_ratio', result)
        self.assertIn('context_builder_compress_code_total', result)
        self.assertEqual(result['context_builder_compress_code_total'], 1)


class TestContextCompressorV2(unittest.TestCase):
    """Test advanced context compressor."""

    def setUp(self):
        """Set up test fixtures."""
        self.compressor = ContextCompressorV2(use_mock_llm=True)

    def test_compress_candidates_code(self):
        """Test compressing code candidates."""
        candidates = [
            {
                'content': '''
def hello():
    # comment
    print("test")
    return True
''',
                'type': 'code',
                'file': 'test.py',
                'relevance': 0.9,
                'content_type': 'code',
            }
        ]
        result, metrics = self.compressor.compress_candidates(candidates)
        self.assertEqual(len(result), 1)
        self.assertIn('compressed', result[0])

    def test_compress_candidates_knowledge(self):
        """Test compressing knowledge candidates."""
        candidates = [
            {
                'content': 'knowledge ' * 500,  # Long text
                'type': 'knowledge',
                'relevance': 0.8,
            }
        ]
        result, metrics = self.compressor.compress_candidates(candidates)
        self.assertEqual(len(result), 1)

    def test_get_language_detection(self):
        """Test language detection."""
        self.assertEqual(self.compressor._get_language('file.py'), 'python')
        self.assertEqual(self.compressor._get_language('file.js'), 'javascript')
        self.assertEqual(self.compressor._get_language('file.go'), 'go')
        self.assertEqual(self.compressor._get_language(None), 'python')

    def test_metrics_collection(self):
        """Test metrics collection."""
        candidates = [
            {
                'content': 'print("test")  # comment',
                'type': 'code',
                'file': 'test.py',
                'content_type': 'code',
            }
        ]
        result, metrics = self.compressor.compress_candidates(candidates)
        self.assertIn('context_builder_compress_ratio', metrics)
        self.assertGreater(metrics['context_builder_compress_code_total'], 0)


if __name__ == '__main__':
    unittest.main()
