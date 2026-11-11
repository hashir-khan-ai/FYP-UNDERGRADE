"""Server-side role filtering shared by the dense and sparse retrieval paths.

The role is always resolved from the authenticated session, never from a request
body. Qdrant applies :func:`get_role_filter` natively, so chunks that do not
carry the caller's role are excluded before vector scoring. BM25 applies the same
rule to candidate metadata before fusion. :func:`enforce_role_visibility` is the
defence-in-depth guard applied again after re-ranking.
"""

from typing import Any

from qdrant_client.http import models as qmodels

VALID_ROLES: tuple[str, ...] = ("analyst", "manager", "auditor")


class InvalidRoleError(ValueError):
    """Raised when a role outside the frozen three-role model is supplied."""


def normalize_role(role: str) -> str:
    """Validate and normalise a role name.

    Args:
        role: Candidate role string.

    Returns:
        The normalised role name.

    Raises:
        InvalidRoleError: if the role is not one of the three project roles.
    """
    normalized = (role or "").strip().lower()
    if normalized not in VALID_ROLES:
        raise InvalidRoleError(f"Unknown role: {role!r}")
    return normalized


def get_role_filter(role: str) -> qmodels.Filter:
    """Build the native Qdrant payload filter for one role.

    Args:
        role: Authenticated user role.

    Returns:
        A filter matching chunks whose ``allowed_roles`` array contains the role.
    """
    return qmodels.Filter(
        must=[
            qmodels.FieldCondition(
                key="allowed_roles",
                match=qmodels.MatchValue(value=normalize_role(role)),
            )
        ]
    )


def chunk_visible_to_role(chunk: dict[str, Any], role: str) -> bool:
    """Return True only when the chunk metadata explicitly allows the role.

    Chunks with missing or empty ``allowed_roles`` are treated as restricted
    (deny by default) so an ingestion bug cannot widen access.
    """
    roles = chunk.get("allowed_roles") or []
    return normalize_role(role) in roles


def enforce_role_visibility(
    passages: list[dict[str, Any]],
    role: str,
) -> tuple[list[dict[str, Any]], int]:
    """Drop any passage that does not allow ``role`` after re-ranking.

    Args:
        passages: Re-ranked passages.
        role: Authenticated user role.

    Returns:
        Tuple of (permitted passages, number dropped).
    """
    permitted: list[dict[str, Any]] = []
    dropped = 0
    for passage in passages:
        if chunk_visible_to_role(passage, role):
            permitted.append(passage)
        else:
            dropped += 1
    return permitted, dropped


__all__ = [
    "VALID_ROLES",
    "InvalidRoleError",
    "chunk_visible_to_role",
    "enforce_role_visibility",
    "get_role_filter",
    "normalize_role",
]
