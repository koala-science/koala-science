"""Koala Science SDK exceptions."""


class CoalescenceError(Exception):
    """Base exception for Koala Science SDK."""
    pass


class AuthError(CoalescenceError):
    """Authentication failed — invalid or expired token/API key."""
    pass


class NotFoundError(CoalescenceError):
    """The requested resource was not found."""
    pass


class RateLimitError(CoalescenceError):
    """Rate limit exceeded — slow down."""
    pass


class ValidationError(CoalescenceError):
    """Request validation failed — check your input."""
    pass
