# Import all the models, so that Base has them before being
# imported by Alembic
from app.db.base_class import Base  # noqa

from app.models.identity import Actor, HumanAccount, DelegatedAgent, SovereignAgent  # noqa
from app.models.platform import (  # noqa
    Paper, Comment, Vote, Domain, Subscription,
    DomainAuthority, InteractionEvent,
)
