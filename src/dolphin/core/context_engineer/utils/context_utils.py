"""Context utility functions."""

import re
from typing import List, Dict, Optional
from ..core.tokenizer_service import TokenizerService


def extract_key_info(
    text: str, max_sentences: int = 3, keyword_weight: float = 2.0
) -> str:
    """
    Extract key information from text using simple heuristics.

    Args:
        text: Input text
        max_sentences: Maximum number of sentences to extract
        keyword_weight: Weight for keyword-containing sentences

    Returns:
        Extracted key information
    """
    if not text:
        return ""

    # Split into sentences
    sentences = re.split(r"[.!?]+", text)
    sentences = [s.strip() for s in sentences if s.strip()]

    if not sentences:
        return ""

    # Simple keyword extraction
    words = re.findall(r"\b\w+\b", text.lower())
    word_freq = {}
    for word in words:
        if len(word) > 3:  # Filter short words
            word_freq[word] = word_freq.get(word, 0) + 1

    # Get top keywords (excluding common words)
    common_words = {
        "the",
        "and",
        "or",
        "but",
        "in",
        "on",
        "at",
        "to",
        "for",
        "of",
        "with",
        "by",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "can",
        "this",
        "that",
        "these",
        "those",
        "a",
        "an",
    }

    keywords = {
        word: freq
        for word, freq in word_freq.items()
        if word not in common_words and freq > 1
    }

    # Score sentences based on keywords and position
    sentence_scores = []
    for i, sentence in enumerate(sentences):
        score = 0
        sentence_lower = sentence.lower()

        # Keyword matches
        for keyword in keywords:
            if keyword in sentence_lower:
                score += keyword_weight * keywords[keyword]

        # Position bonus (first and last sentences get higher scores)
        if i == 0 or i == len(sentences) - 1:
            score += 1.0

        sentence_scores.append((i, sentence, score))

    # Sort by score and take top sentences
    sentence_scores.sort(key=lambda x: x[2], reverse=True)
    top_sentences = sentence_scores[:max_sentences]
    top_sentences.sort(key=lambda x: x[0])  # Restore original order

    return ". ".join(sentence for _, sentence, _ in top_sentences) + "."


def summarize_content(
    text: str, target_ratio: float = 0.3, preserve_keywords: bool = True
) -> str:
    """
    Summarize content by extracting key sentences and compressing.

    Args:
        text: Input text
        target_ratio: Target compression ratio
        preserve_keywords: Whether to preserve important keywords

    Returns:
        Summarized content
    """
    if not text:
        return ""

    # Extract key information first
    key_info = extract_key_info(text, max_sentences=int(1 / target_ratio))

    if preserve_keywords:
        # Extract keywords from original text
        words = re.findall(r"\b\w+\b", text.lower())
        word_freq = {}
        for word in words:
            if len(word) > 4:  # Filter short words
                word_freq[word] = word_freq.get(word, 0) + 1

        # Get top keywords
        keywords = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)[:10]
        keyword_list = [word for word, freq in keywords if freq > 1]

        # Ensure keywords are included in summary
        summary_parts = [key_info]

        # Add keyword context if not already included
        for keyword in keyword_list[:5]:  # Top 5 keywords
            if keyword not in key_info.lower():
                # Find a sentence containing this keyword
                sentences = re.split(r"[.!?]+", text)
                for sentence in sentences:
                    if keyword in sentence.lower():
                        summary_parts.append(sentence.strip())
                        break

        return " ".join(summary_parts)

    return key_info


def extract_entities(text: str) -> Dict[str, List[str]]:
    """
    Simple entity extraction using regex patterns.

    Args:
        text: Input text

    Returns:
        Dictionary of extracted entities by type
    """
    entities = {"dates": [], "emails": [], "urls": [], "numbers": [], "cap_words": []}

    if not text:
        return entities

    # Date patterns
    date_patterns = [
        r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b",  # MM/DD/YYYY or DD-MM-YYYY
        r"\b\d{4}[/-]\d{1,2}[/-]\d{1,2}\b",  # YYYY/MM/DD
        r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}\b",  # Month DD, YYYY
    ]

    for pattern in date_patterns:
        entities["dates"].extend(re.findall(pattern, text, re.IGNORECASE))

    # Email patterns
    entities["emails"] = re.findall(
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", text
    )

    # URL patterns
    entities["urls"] = re.findall(
        r"http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+",
        text,
    )

    # Number patterns
    entities["numbers"] = re.findall(r"\b\d+(?:\.\d+)?\b", text)

    # Capitalized words (potential proper nouns)
    cap_words = re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b", text)
    entities["cap_words"] = list(set(cap_words))  # Remove duplicates

    # Remove duplicates from other lists too
    for key in entities:
        entities[key] = list(set(entities[key]))

    return entities


def calculate_relevance_score(
    query: str, content: str, tokenizer_service: Optional[TokenizerService] = None
) -> float:
    """
    Calculate relevance score between query and content.

    Args:
        query: Search query or task description
        content: Content to score
        tokenizer_service: TokenizerService instance

    Returns:
        Relevance score (0-1)
    """
    if not query or not content:
        return 0.0

    # Simple keyword-based relevance
    query_words = set(re.findall(r"\b\w+\b", query.lower()))
    content_words = set(re.findall(r"\b\w+\b", content.lower()))

    # Remove common words
    common_words = {
        "the",
        "and",
        "or",
        "but",
        "in",
        "on",
        "at",
        "to",
        "for",
        "of",
        "with",
        "by",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "can",
        "this",
        "that",
        "these",
        "those",
        "a",
        "an",
        "it",
        "its",
        "they",
        "them",
        "their",
        "we",
        "us",
        "our",
        "you",
        "your",
    }

    query_keywords = query_words - common_words
    content_keywords = content_words - common_words

    if not query_keywords:
        return 0.0

    # Calculate overlap
    overlap = len(query_keywords.intersection(content_keywords))
    total_unique = len(query_keywords.union(content_keywords))

    # Jaccard similarity
    jaccard = overlap / total_unique if total_unique > 0 else 0.0

    # Bonus for exact phrase matches
    phrase_bonus = 0.0
    query_phrases = re.findall(r'"([^"]+)"', query)
    for phrase in query_phrases:
        if phrase.lower() in content.lower():
            phrase_bonus += 0.2

    return min(1.0, jaccard + phrase_bonus)


def extract_task_keywords(task_description: str) -> List[str]:
    """
    Extract keywords from task description.

    Args:
        task_description: Task description text

    Returns:
        List of extracted keywords
    """
    if not task_description:
        return []

    # Extract action verbs and important nouns
    words = re.findall(r"\b\w+\b", task_description.lower())

    # Common action verbs in tasks
    action_verbs = {
        "analyze",
        "create",
        "generate",
        "find",
        "search",
        "extract",
        "summarize",
        "compare",
        "evaluate",
        "assess",
        "review",
        "examine",
        "investigate",
        "determine",
        "identify",
        "classify",
        "organize",
        "optimize",
        "improve",
        "fix",
        "solve",
        "calculate",
        "compute",
        "predict",
        "recommend",
        "suggest",
    }

    # Technical terms (expand as needed)
    tech_terms = {
        "data",
        "algorithm",
        "model",
        "function",
        "variable",
        "database",
        "api",
        "json",
        "xml",
        "html",
        "css",
        "javascript",
        "python",
        "code",
        "program",
        "software",
        "system",
        "architecture",
        "design",
        "implementation",
        "testing",
        "debugging",
    }

    keywords = []
    for word in words:
        if len(word) > 3 and (word in action_verbs or word in tech_terms):
            keywords.append(word)

    # Remove duplicates while preserving order
    seen = set()
    unique_keywords = []
    for keyword in keywords:
        if keyword not in seen:
            seen.add(keyword)
            unique_keywords.append(keyword)

    return unique_keywords[:10]  # Return top 10 keywords


def format_context_section(
    name: str, content: str, max_length: Optional[int] = None
) -> str:
    """
    Format a context section with proper headers and structure.

    Args:
        name: Section name
        content: Section content
        max_length: Maximum length for content (will truncate if exceeded)

    Returns:
        Formatted section
    """
    if not content:
        return ""

    # Truncate if necessary
    if max_length and len(content) > max_length:
        content = content[: max_length - 3] + "..."

    # Format with header
    formatted = f"### {name.upper()} ###\n{content}"

    return formatted


def merge_context_sections(sections: Dict[str, str], separator: str = "\n\n") -> str:
    """
    Merge multiple context sections into a single string.

    Args:
        sections: Dictionary of section names to content
        separator: Separator between sections

    Returns:
        Merged context string
    """
    if not sections:
        return ""

    parts = []
    for name, content in sections.items():
        if content and content.strip():
            formatted_section = format_context_section(name, content.strip())
            parts.append(formatted_section)

    return separator.join(parts)
