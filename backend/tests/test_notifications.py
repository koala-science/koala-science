"""Domain subscriptions, and the "new paper in your domain" notification, are gone.

Subscribing to a domain did nothing but trigger that notification, so both
were removed together. The only notifications left are about an agent's
own arguments.
"""
import uuid

from httpx import AsyncClient

from app.models.notification import NotificationType
from tests.conftest import complete_signup


async def _signup(client: AsyncClient) -> tuple[str, str]:
    return await complete_signup(client, {
        "name": "No Subs",
        "email": f"nosubs_{uuid.uuid4().hex[:8]}@example.com",
        "password": "secure_password_123",
        "openreview_id": f"~No_Subs_{uuid.uuid4().hex[:8]}1",
    })


def test_only_argument_notifications_remain():
    assert {t.value for t in NotificationType} == {
        "ARGUMENT_ACCEPTED", "ARGUMENT_REJECTED", "AUTHOR_RESPONDED",
    }


async def test_the_subscription_endpoints_are_gone(client: AsyncClient):
    token, _ = await _signup(client)
    headers = {"Authorization": f"Bearer {token}"}
    domain_id = uuid.uuid4()

    assert (await client.post(f"/api/v1/domains/{domain_id}/subscribe", headers=headers)).status_code == 405
    assert (await client.delete(f"/api/v1/domains/{domain_id}/subscribe", headers=headers)).status_code == 405
    assert (await client.get("/api/v1/users/me/subscriptions", headers=headers)).status_code == 404


def test_the_subscription_model_is_gone():
    """CI builds its schema from the models, so this guards that nothing maps the table.

    Dropping it from existing databases is migration 069's job.
    """
    from app.db.base import Base

    assert "paper" in Base.metadata.tables, "could not read the model metadata"
    assert "subscription" not in Base.metadata.tables
