"""
Utility functions for the memory management system.
"""

from dolphin.core.common.enums import KnowledgePoint


def validate_knowledge_point(
    data: KnowledgePoint, expected_user_id: str = None
) -> KnowledgePoint:
    """
    Validate and convert raw data to KnowledgePoint.

    :param data: Raw dictionary data
    :param expected_user_id: Expected user_id for validation (optional)
    :return: Validated KnowledgePoint
    :raises KnowledgeValidationError: If validation fails
    """
    if data.type not in ["WorldModel", "ExperientialKnowledge", "OtherKnowledge"]:
        raise Exception(f"Invalid knowledge type: {data.type}")

    if not isinstance(data.score, int) or not (0 <= data.score <= 100):
        raise Exception(f"Score must be integer between 0-100: {data['score']}")

    if expected_user_id and data.user_id != expected_user_id:
        raise Exception(
            f"User ID mismatch: expected {expected_user_id}, got {data.user_id}"
        )

    return KnowledgePoint(
        content=str(data.content),
        type=data.type,
        score=int(data.score),
        user_id=str(data.user_id),
        metadata=data.metadata,
    )


def sanitize_user_id(user_id: str) -> str:
    """
    Sanitize user_id for safe filesystem usage.

    :param user_id: Raw user ID
    :return: Sanitized user ID safe for filesystem
    """
    # Remove or replace potentially problematic characters
    # Allow only word characters, hyphens, and underscores
    import re

    sanitized = re.sub(r"[^\w\-_]", "_", user_id)
    return sanitized[:50]  # Limit length to avoid filesystem issues
