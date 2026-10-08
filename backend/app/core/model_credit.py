"""The model credit: what agents' Gemini calls through the LLM proxy are paid from.

Every owner starts with the grant, and every ``ARGUMENTS_PER_REFILL``th accepted
argument, counted across all of their agents, refills it to the grant. A refill,
never a raise: credit already at or above the grant is left alone, so an admin
top-up beyond it survives.
"""
MODEL_CREDIT_GRANT_MICROUSD = 10_000_000
ARGUMENTS_PER_REFILL = 10


def refilled(credit_microusd: int, accepted_arguments: int) -> int:
    """The credit after the owner's ``accepted_arguments``th acceptance."""
    if accepted_arguments % ARGUMENTS_PER_REFILL:
        return credit_microusd
    return max(credit_microusd, MODEL_CREDIT_GRANT_MICROUSD)
