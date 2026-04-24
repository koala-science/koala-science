"""DELETE /papers/{paper_id} is not exposed during the competition.

Papers must not be deletable via the API while the Mila agent-review
competition is live — removing a paper would wipe reviewers' scored
engagement and open a trivial manipulation vector.
"""
import uuid

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_delete_paper_endpoint_not_exposed(client: AsyncClient):
    response = await client.delete(f"/api/v1/papers/{uuid.uuid4()}")
    assert response.status_code == 405
