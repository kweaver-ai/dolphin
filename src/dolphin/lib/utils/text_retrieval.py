"""Text Retrieval Utilities

Shared text retrieval related tools, including:
- Tokenizer
- BM25Index - based on rank_bm25
- VectorUtils

Shared for use by modules such as memory_skillkit and local_retrieval_skillkit
"""

import os
import re
from typing import Dict, List, Optional, Tuple
import math
from collections import Counter

# Allow forcing the use of pure Python BM25 via environment variable to avoid C extension issues in specific environments
_FORCE_PURE_PY = os.getenv("FORCE_PURE_PY_BM25", "").strip() == "1"
try:
    if _FORCE_PURE_PY:
        raise ImportError("FORCE_PURE_PY_BM25=1")
    from rank_bm25 import BM25Okapi

    _HAS_RANK_BM25 = True
except ImportError:
    _HAS_RANK_BM25 = False
    BM25Okapi = None


# -----------------------------
# Tokenizer Tool
# -----------------------------

_WORD_RE = re.compile(r"[A-Za-z0-9_]+", re.UNICODE)


def is_cjk(ch: str) -> bool:
    """Detect whether a character is a CJK character (Chinese, Japanese, Korean characters)"""
    code = ord(ch)
    return (
        0x4E00 <= code <= 0x9FFF  # CJK Unified Ideographs
        or 0x3400 <= code <= 0x4DBF  # CJK Extension A
        or 0x20000 <= code <= 0x2A6DF  # CJK Extension B
        or 0x2A700 <= code <= 0x2B73F  # CJK Extension C
        or 0x2B740 <= code <= 0x2B81F  # CJK Extension D
        or 0x2B820 <= code <= 0x2CEAF  # CJK Extension E
        or 0xF900 <= code <= 0xFAFF  # CJK Compatibility Ideographs
        or 0x2F800 <= code <= 0x2FA1F  # CJK Compatibility Ideographs Supplement
        or 0xAC00 <= code <= 0xD7AF  # Hangul Syllables (Korean)
        or 0x1100 <= code <= 0x11FF  # Hangul Jamo
        or 0x3130 <= code <= 0x318F  # Hangul Compatibility Jamo
        or 0xA960 <= code <= 0xA97F  # Hangul Jamo Extended-A
        or 0xD7B0 <= code <= 0xD7FF  # Hangul Jamo Extended-B
    )


def tokenize_simple(text: str) -> List[str]:
    """Simple tokenizer: supports ASCII words and CJK characters

        - ASCII words are split by non-word characters and converted to lowercase
        - CJK characters are treated as individual tokens (unigram)
    """
    if not text:
        return []

    tokens: List[str] = []
    buf: List[str] = []

    for ch in text:
        if is_cjk(ch):
            if buf:
                word = "".join(buf).lower()
                if word:
                    tokens.append(word)
                buf.clear()
            tokens.append(ch)
        elif ch.isalnum() or ch == "_":
            buf.append(ch)
        else:
            if buf:
                word = "".join(buf).lower()
                if word:
                    tokens.append(word)
                buf.clear()

    if buf:
        word = "".join(buf).lower()
        if word:
            tokens.append(word)

    return tokens


def tokenize_bigram_cjk(text: str) -> List[str]:
    """Double-byte CJK tokenizer: supports double-byte Chinese segmentation"""
    text = text.lower()
    # Keep Chinese, English, and numbers, convert other characters to spaces
    text = re.sub(r"[^\w\u4e00-\u9fff]+", " ", text)

    tokens = []
    for chunk in text.split():
        # Check if it contains Chinese
        if re.search(r"[\u4e00-\u9fff]", chunk):
            # Chinese text using bigram (two-byte) segmentation
            if len(chunk) >= 2:
                tokens.extend([chunk[i : i + 2] for i in range(len(chunk) - 1)])
            elif len(chunk) == 1:
                tokens.append(chunk)
        else:
            # English/numbers keep original words
            if len(chunk) > 1:
                tokens.append(chunk)

    return tokens


# -----------------------------
# BM25 Index
# -----------------------------


class BM25Index:
    """BM25 index implementation, based on the rank_bm25 library"""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        if not _HAS_RANK_BM25:
            raise ImportError(
                "rank_bm25 is required. Install with: pip install rank-bm25"
            )

        self.k1 = k1
        self.b = b
        self._bm25_index = None  # rank_bm25 instance (if available)
        self._doc_ids: List[int] = []
        self._tokenizer_func = tokenize_simple

        # Required structures for pure Python fallback implementation
        self._tokenized_docs: List[List[str]] = []
        self._tf_docs: List[Counter] = []
        self._idf: Dict[str, float] = {}
        self._doc_lens: List[int] = []
        self._avgdl: float = 0.0

    def build_from_corpus(self, documents: Dict[int, str], tokenizer_func=None) -> None:
        """Build index from document corpus"""
        if tokenizer_func is None:
            tokenizer_func = tokenize_simple

        self._tokenizer_func = tokenizer_func
        self._doc_ids = list(documents.keys())

        # Handling empty document collections
        if not documents:
            self._bm25_index = None
            self._tokenized_docs = []
            self._tf_docs = []
            self._idf = {}
            self._doc_lens = []
            self._avgdl = 0.0
            return

        # Tokenization Processing
        tokenized_docs = []
        for doc_id in self._doc_ids:
            tokens = tokenizer_func(documents[doc_id])
            tokenized_docs.append(tokens)

        if _HAS_RANK_BM25:
            # Build BM25 index (C extension/third-party library)
            self._bm25_index = BM25Okapi(tokenized_docs, k1=self.k1, b=self.b)
            # Clear rollback structure
            self._tokenized_docs = []
            self._tf_docs = []
            self._idf = {}
            self._doc_lens = []
            self._avgdl = 0.0
        else:
            # Pure Python fallback implementation
            self._bm25_index = None
            self._tokenized_docs = tokenized_docs
            self._tf_docs = [Counter(doc) for doc in tokenized_docs]
            self._doc_lens = [len(doc) for doc in tokenized_docs]
            self._avgdl = (
                sum(self._doc_lens) / len(self._doc_lens) if self._doc_lens else 0.0
            )

            # Calculate idf
            N = len(tokenized_docs)
            df: Counter = Counter()
            for doc in tokenized_docs:
                df.update(set(doc))
            self._idf = {}
            for term, dfi in df.items():
                # Smooth IDF consistent with common implementations
                self._idf[term] = math.log((N - dfi + 0.5) / (dfi + 0.5) + 1)

    def search(
        self,
        query: str,
        allowed_doc_ids: Optional[set] = None,
        topk: int = 10,
        tokenizer_func=None,
    ) -> List[Tuple[int, float]]:
        """Search related documents"""
        # If there is no rank_bm25 instance and no fallback index data, return empty
        if self._bm25_index is None and not self._tf_docs:
            return []

        if tokenizer_func is None:
            tokenizer_func = self._tokenizer_func

        query_tokens = tokenizer_func(query)
        if not query_tokens:
            return []

        if _HAS_RANK_BM25 and self._bm25_index is not None:
            scores = self._bm25_index.get_scores(query_tokens)
        else:
            # Pure Python BM25 Scoring
            scores = [0.0] * len(self._doc_ids)
            for i, tf in enumerate(self._tf_docs):
                dl = self._doc_lens[i] if self._doc_lens else 0
                for term in query_tokens:
                    if term not in self._idf:
                        continue
                    tf_i = tf.get(term, 0)
                    if tf_i == 0:
                        continue
                    idf = self._idf[term]
                    denom = tf_i + self.k1 * (
                        1
                        - self.b
                        + self.b * (dl / self._avgdl if self._avgdl > 0 else 0)
                    )
                    score = idf * (tf_i * (self.k1 + 1)) / denom
                    scores[i] += score

        # Combine doc_id and score, return only documents with associations
        # A BM25 score of 0 indicates that the document does not contain the query term and can be filtered out.
        results = []
        for i, score in enumerate(scores):
            if score != 0.0:  # Filter out irrelevant documents
                doc_id = self._doc_ids[i]
                if allowed_doc_ids is None or doc_id in allowed_doc_ids:
                    results.append((doc_id, float(score)))

        # Sort and return the topk results
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:topk]

    def add_or_update(self, doc_id: int, text: str, tokenizer_func=None) -> None:
        """Add or update a single document (requires rebuilding the entire index)"""
        # For dynamic updates, we need to rebuild the index.
        # This is a limitation of rank_bm25, but it is acceptable for most scenarios.

        # If the index does not exist, create a new one.
        if self._bm25_index is None:
            documents = {doc_id: text}
            self.build_from_corpus(documents, tokenizer_func)
            return

        # Otherwise, the index needs to be rebuilt (can be optimized to incremental updates, but will increase complexity)
        raise NotImplementedError(
            "Dynamic update requires rebuilding the index. Use build_from_corpus instead."
        )

    def remove(self, doc_id: int) -> None:
        """Delete document (requires rebuilding the entire index)"""
        raise NotImplementedError(
            "Document removal requires rebuilding the index. Use build_from_corpus instead."
        )

    @property
    def N(self) -> int:
        """Total number of documents"""
        return len(self._doc_ids) if self._doc_ids else 0

    # Backward-compatible aliases
    def search_optimized(
        self,
        query: str,
        allowed_doc_ids: Optional[set] = None,
        topk: int = 10,
        tokenizer_func=None,
    ) -> List[Tuple[int, float]]:
        """Alias for optimized search"""
        return self.search(query, allowed_doc_ids, topk, tokenizer_func)


# -----------------------------
# Vector Calculation Tools
# -----------------------------


class VectorUtils:
    """Vector calculation utility class"""

    @staticmethod
    def cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
        """Calculate cosine similarity"""
        if len(vec1) != len(vec2):
            return 0.0

        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = sum(a * a for a in vec1) ** 0.5
        norm2 = sum(b * b for b in vec2) ** 0.5

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return dot_product / (norm1 * norm2)

    @staticmethod
    def euclidean_distance(vec1: List[float], vec2: List[float]) -> float:
        """Calculate Euclidean distance"""
        if len(vec1) != len(vec2):
            return float("inf")

        return sum((a - b) ** 2 for a, b in zip(vec1, vec2)) ** 0.5

    @staticmethod
    def normalize_l2(vec: List[float]) -> List[float]:
        """L2 normalization"""
        norm = sum(v * v for v in vec) ** 0.5
        if norm > 0:
            return [v / norm for v in vec]
        return vec.copy()

    @staticmethod
    def compute_simple_embedding(
        text: str, dim: int = 384, tokenizer_func=None
    ) -> List[float]:
        """Simple embedding implementation based on hash (fallback solution)"""
        import hashlib

        if tokenizer_func is None:
            tokenizer_func = tokenize_simple

        vec = [0.0] * dim
        tokens = tokenizer_func(text) or [""]

        for tok in tokens:
            h = hashlib.md5(tok.encode("utf-8")).digest()
            # Generate multiple indices and weights using the first 16 bytes
            idx1 = int.from_bytes(h[:4], "big") % dim
            idx2 = int.from_bytes(h[4:8], "big") % dim
            w1 = (int.from_bytes(h[8:12], "big") % 100) / 100.0 + 1.0
            w2 = (int.from_bytes(h[12:16], "big") % 100) / 100.0 + 0.5
            vec[idx1] += w1
            vec[idx2] += w2

        return VectorUtils.normalize_l2(vec)


# -----------------------------
# Hybrid Retrieval Tool
# -----------------------------


class HybridRetriever:
    """Hybrid Retriever: Combining BM25 and Vector Similarity"""

    def __init__(self, bm25_weight: float = 0.7):
        self.bm25_weight = bm25_weight
        self.embedding_weight = 1.0 - bm25_weight

    def combine_scores(
        self,
        bm25_results: List[Tuple[int, float]],
        embedding_results: List[Tuple[int, float]],
    ) -> List[Tuple[int, float]]:
        """Combining BM25 and embedding scores"""
        bm25_dict = dict(bm25_results)
        embedding_dict = dict(embedding_results)

        # Get all document IDs
        all_doc_ids = set(bm25_dict.keys()) | set(embedding_dict.keys())

        if not all_doc_ids:
            return []

        # Fraction Normalization
        def minmax_normalize(scores: List[float]) -> List[float]:
            if not scores:
                return scores
            min_s, max_s = min(scores), max(scores)
            if max_s == min_s:
                return [1.0] * len(scores)
            return [(s - min_s) / (max_s - min_s) for s in scores]

        bm25_scores = list(bm25_dict.values())
        embedding_scores = list(embedding_dict.values())

        # Normalize only when there are scores.
        bm25_normalized = {}
        if bm25_scores:
            bm25_norm_scores = minmax_normalize(bm25_scores)
            bm25_normalized = dict(zip(bm25_dict.keys(), bm25_norm_scores))

        embedding_normalized = {}
        if embedding_scores:
            emb_norm_scores = minmax_normalize(embedding_scores)
            embedding_normalized = dict(zip(embedding_dict.keys(), emb_norm_scores))

        # Combined Score
        combined_results = []
        for doc_id in all_doc_ids:
            bm25_score = bm25_normalized.get(doc_id, 0.0)
            emb_score = embedding_normalized.get(doc_id, 0.0)
            combined_score = (
                self.bm25_weight * bm25_score + self.embedding_weight * emb_score
            )
            combined_results.append((doc_id, combined_score))

        return sorted(combined_results, key=lambda x: x[1], reverse=True)


# -----------------------------
# Convenience functions
# -----------------------------


def create_bm25_index(
    documents: Dict[int, str],
    tokenizer: str = "simple",
    k1: float = 1.5,
    b: float = 0.75,
) -> BM25Index:
    """Convenience function: Create BM25 index

        Args:
            documents: Document dictionary {doc_id: content}
            tokenizer: Tokenizer type ("simple", "bigram_cjk")
            k1, b: BM25 parameters
    """
    tokenizer_func = {
        "simple": tokenize_simple,
        "bigram_cjk": tokenize_bigram_cjk,
    }.get(tokenizer, tokenize_simple)

    index = BM25Index(k1=k1, b=b)
    index.build_from_corpus(documents, tokenizer_func)
    return index


def search_documents(
    index: BM25Index, query: str, topk: int = 10, tokenizer: str = "simple"
) -> List[Tuple[int, float]]:
    """Convenient function: search documents

        Args:
            index: BM25 index
            query: query string
            topk: number of results to return
            tokenizer: tokenizer type
    """
    tokenizer_func = {
        "simple": tokenize_simple,
        "bigram_cjk": tokenize_bigram_cjk,
    }.get(tokenizer, tokenize_simple)

    return index.search(query, topk=topk, tokenizer_func=tokenizer_func)
