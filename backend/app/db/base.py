# Import all the models, so that Base has them before being
# imported by Alembic
from app.db.base_class import Base  # noqa

from app.models.identity import Actor, HumanAccount, Agent  # noqa
from app.models.platform import (  # noqa
    Paper, Domain, Subscription, InteractionEvent, Argument, ArgumentCheck,
    ArgumentEmbedding, CheckFlag,
)
from app.models.notification import Notification  # noqa
