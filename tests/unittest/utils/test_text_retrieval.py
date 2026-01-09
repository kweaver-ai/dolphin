import unittest

from dolphin.lib.utils.text_retrieval import (
    tokenize_simple,
    tokenize_bigram_cjk,
    is_cjk,
    BM25Index,
    VectorUtils,
    HybridRetriever,
    create_bm25_index,
    search_documents,
)


class TestTokenization(unittest.TestCase):
    """Test tokenization functions"""

    def test_is_cjk(self):
        # Test Chinese characters
        self.assertTrue(is_cjk("中"))
        self.assertTrue(is_cjk("文"))

        # Test Korean characters
        self.assertTrue(is_cjk("한"))
        self.assertTrue(is_cjk("국"))

        # Test Japanese characters
        self.assertTrue(is_cjk("日"))
        self.assertTrue(is_cjk("本"))

        # Test non-CJK characters
        self.assertFalse(is_cjk("a"))
        self.assertFalse(is_cjk("1"))
        self.assertFalse(is_cjk(" "))
        self.assertFalse(is_cjk("!"))

    def test_tokenize_simple_english(self):
        tokens = tokenize_simple("Hello World 123")
        self.assertEqual(tokens, ["hello", "world", "123"])

    def test_tokenize_simple_cjk(self):
        tokens = tokenize_simple("你好世界")
        self.assertEqual(tokens, ["你", "好", "世", "界"])

    def test_tokenize_simple_mixed(self):
        tokens = tokenize_simple("Hello 世界 123")
        self.assertEqual(tokens, ["hello", "世", "界", "123"])

    def test_tokenize_simple_empty(self):
        self.assertEqual(tokenize_simple(""), [])
        self.assertEqual(tokenize_simple("   "), [])

    def test_tokenize_simple_punctuation(self):
        tokens = tokenize_simple("hello, world!")
        self.assertEqual(tokens, ["hello", "world"])

    def test_tokenize_bigram_cjk(self):
        tokens = tokenize_bigram_cjk("你好世界")
        expected = ["你好", "好世", "世界"]
        self.assertEqual(tokens, expected)

    def test_tokenize_bigram_english(self):
        tokens = tokenize_bigram_cjk("hello world")
        self.assertEqual(tokens, ["hello", "world"])

    def test_tokenize_bigram_mixed(self):
        tokens = tokenize_bigram_cjk("hello 世界 test")
        # Should include: hello, 世界 (bigram), test
        self.assertIn("hello", tokens)
        self.assertIn("世界", tokens)
        self.assertIn("test", tokens)


class TestBM25Index(unittest.TestCase):
    """Test BM25 index functionality"""

    def setUp(self):
        self.index = BM25Index()

    def test_empty_index(self):
        results = self.index.search("test")
        self.assertEqual(results, [])

    def test_add_document(self):
        # 新的BM25Index不支持单个文档添加，需要使用build_from_corpus
        documents = {1: "hello world"}
        self.index.build_from_corpus(documents, tokenize_simple)
        self.assertEqual(self.index.N, 1)

    def test_search_single_doc(self):
        documents = {1: "hello world"}
        self.index.build_from_corpus(documents, tokenize_simple)
        results = self.index.search("hello", tokenizer_func=tokenize_simple)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][0], 1)  # doc_id
        self.assertIsInstance(results[0][1], float)  # score is a float

    def test_search_multiple_docs(self):
        documents = {1: "hello world", 2: "world peace", 3: "hello peace"}
        self.index.build_from_corpus(documents, tokenize_simple)

        results = self.index.search("hello", topk=10, tokenizer_func=tokenize_simple)
        doc_ids = [r[0] for r in results]
        self.assertIn(1, doc_ids)
        self.assertIn(3, doc_ids)
        self.assertNotIn(2, doc_ids)

    def test_update_document(self):
        # 测试更新文档（通过重建索引实现）
        documents = {1: "hello world"}
        self.index.build_from_corpus(documents, tokenize_simple)

        results = self.index.search("hello", tokenizer_func=tokenize_simple)
        self.assertEqual(len(results), 1)

        # 更新文档内容
        updated_documents = {1: "goodbye world"}
        self.index.build_from_corpus(updated_documents, tokenize_simple)

        results = self.index.search("hello", tokenizer_func=tokenize_simple)
        self.assertEqual(len(results), 0)  # "hello" not in "goodbye world"

        results = self.index.search("goodbye", tokenizer_func=tokenize_simple)
        self.assertEqual(len(results), 1)

    def test_remove_document(self):
        # 测试删除文档（通过重建索引实现）
        documents = {1: "hello world", 2: "world peace"}
        self.index.build_from_corpus(documents, tokenize_simple)

        # "删除"文档1（重建时不包含）
        updated_documents = {2: "world peace"}
        self.index.build_from_corpus(updated_documents, tokenize_simple)
        self.assertEqual(self.index.N, 1)

        results = self.index.search("hello", tokenizer_func=tokenize_simple)
        self.assertEqual(len(results), 0)  # "hello" not in remaining document

        results = self.index.search("world", tokenizer_func=tokenize_simple)
        self.assertEqual(len(results), 1)

    def test_allowed_doc_ids(self):
        documents = {1: "hello world", 2: "hello universe"}
        self.index.build_from_corpus(documents, tokenize_simple)

        results = self.index.search(
            "hello", allowed_doc_ids={1}, tokenizer_func=tokenize_simple
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][0], 1)

    def test_build_from_corpus(self):
        documents = {1: "hello world", 2: "world peace", 3: "hello peace"}

        self.index.build_from_corpus(documents, tokenize_simple)
        self.assertEqual(self.index.N, 3)

        results = self.index.search("hello", tokenizer_func=tokenize_simple)
        doc_ids = [r[0] for r in results]
        self.assertIn(1, doc_ids)
        self.assertIn(3, doc_ids)

    def test_search_optimized(self):
        documents = {1: "hello world", 2: "world peace", 3: "hello peace"}

        self.index.build_from_corpus(documents, tokenize_simple)
        results = self.index.search("hello", topk=2, tokenizer_func=tokenize_simple)

        self.assertLessEqual(len(results), 2)
        for doc_id, score in results:
            self.assertIn(doc_id, [1, 3])
            self.assertIsInstance(score, float)


class TestVectorUtils(unittest.TestCase):
    """Test vector utility functions"""

    def test_cosine_similarity(self):
        vec1 = [1, 0, 0]
        vec2 = [1, 0, 0]
        similarity = VectorUtils.cosine_similarity(vec1, vec2)
        self.assertAlmostEqual(similarity, 1.0, places=5)

        vec1 = [1, 0, 0]
        vec2 = [0, 1, 0]
        similarity = VectorUtils.cosine_similarity(vec1, vec2)
        self.assertAlmostEqual(similarity, 0.0, places=5)

    def test_cosine_similarity_different_lengths(self):
        vec1 = [1, 0]
        vec2 = [1, 0, 0]
        similarity = VectorUtils.cosine_similarity(vec1, vec2)
        self.assertEqual(similarity, 0.0)

    def test_euclidean_distance(self):
        vec1 = [0, 0, 0]
        vec2 = [1, 0, 0]
        distance = VectorUtils.euclidean_distance(vec1, vec2)
        self.assertAlmostEqual(distance, 1.0, places=5)

    def test_euclidean_distance_different_lengths(self):
        vec1 = [0, 0]
        vec2 = [1, 0, 0]
        distance = VectorUtils.euclidean_distance(vec1, vec2)
        self.assertEqual(distance, float("inf"))

    def test_normalize_l2(self):
        vec = [3, 4, 0]
        normalized = VectorUtils.normalize_l2(vec)
        expected = [0.6, 0.8, 0.0]
        for a, b in zip(normalized, expected):
            self.assertAlmostEqual(a, b, places=5)

    def test_normalize_l2_zero_vector(self):
        vec = [0, 0, 0]
        normalized = VectorUtils.normalize_l2(vec)
        self.assertEqual(normalized, [0, 0, 0])

    def test_compute_simple_embedding(self):
        text = "hello world"
        embedding = VectorUtils.compute_simple_embedding(text, dim=10)

        self.assertEqual(len(embedding), 10)
        self.assertTrue(all(isinstance(x, float) for x in embedding))

        # Same text should produce same embedding
        embedding2 = VectorUtils.compute_simple_embedding(text, dim=10)
        self.assertEqual(embedding, embedding2)

        # Different text should produce different embedding
        embedding3 = VectorUtils.compute_simple_embedding("goodbye world", dim=10)
        self.assertNotEqual(embedding, embedding3)


class TestHybridRetriever(unittest.TestCase):
    """Test hybrid retrieval functionality"""

    def setUp(self):
        self.retriever = HybridRetriever(bm25_weight=0.7)

    def test_combine_scores(self):
        bm25_results = [(1, 0.8), (2, 0.6), (3, 0.4)]
        embedding_results = [(1, 0.5), (2, 0.9), (4, 0.7)]

        combined = self.retriever.combine_scores(bm25_results, embedding_results)

        # Should include all documents
        doc_ids = [doc_id for doc_id, _ in combined]
        self.assertIn(1, doc_ids)
        self.assertIn(2, doc_ids)
        self.assertIn(3, doc_ids)
        self.assertIn(4, doc_ids)

        # Should be sorted by score (descending)
        scores = [score for _, score in combined]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_combine_scores_empty(self):
        combined = self.retriever.combine_scores([], [])
        self.assertEqual(combined, [])

    def test_combine_scores_single_source(self):
        bm25_results = [(1, 0.8), (2, 0.6)]
        combined = self.retriever.combine_scores(bm25_results, [])

        # Should still work with only one source
        self.assertEqual(len(combined), 2)
        doc_ids = [doc_id for doc_id, _ in combined]
        self.assertIn(1, doc_ids)
        self.assertIn(2, doc_ids)


class TestConvenienceFunctions(unittest.TestCase):
    """Test convenience functions"""

    def test_create_bm25_index(self):
        documents = {1: "hello world", 2: "world peace", 3: "hello peace"}

        index = create_bm25_index(documents, tokenizer="simple")
        self.assertIsInstance(index, BM25Index)
        self.assertEqual(index.N, 3)

    def test_create_bm25_index_bigram(self):
        documents = {1: "你好世界", 2: "世界和平"}

        index = create_bm25_index(documents, tokenizer="bigram_cjk")
        self.assertIsInstance(index, BM25Index)
        self.assertEqual(index.N, 2)

    def test_search_documents(self):
        documents = {1: "hello world", 2: "world peace", 3: "hello peace"}

        index = create_bm25_index(documents)
        results = search_documents(index, "hello", topk=5)

        doc_ids = [doc_id for doc_id, _ in results]
        self.assertIn(1, doc_ids)
        self.assertIn(3, doc_ids)
        self.assertNotIn(2, doc_ids)


class TestPerformance(unittest.TestCase):
    """Performance-related tests"""

    def test_large_document_set(self):
        """Test with a larger set of documents"""
        documents = {}
        for i in range(100):
            documents[i] = f"document {i} with some content about topic {i % 10}"

        index = create_bm25_index(documents)
        self.assertEqual(index.N, 100)

        results = search_documents(index, "topic 5", topk=20)
        # Should find documents mentioning "topic 5"
        self.assertGreater(len(results), 0)

        # Verify results are sorted by score
        scores = [score for _, score in results]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_empty_and_edge_cases(self):
        """Test edge cases"""
        # Empty documents
        index = create_bm25_index({})
        results = search_documents(index, "test")
        self.assertEqual(results, [])

        # Single document
        index = create_bm25_index({1: "single document"})
        results = search_documents(index, "single")
        self.assertEqual(len(results), 1)

        # Empty query
        results = search_documents(index, "")
        self.assertEqual(results, [])


if __name__ == "__main__":
    unittest.main()
