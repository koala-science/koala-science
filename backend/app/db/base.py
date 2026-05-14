# Import all the models, so that Base has them before being
# imported by Alembic
from app.db.base_class import Base  # noqa

from app.models.identity import Actor, HumanAccount, Agent, OpenReviewId, EmailVerificationToken  # noqa
from app.models.platform import (  # noqa
    Paper, Comment, Verdict, Domain, Subscription, InteractionEvent,
)
from app.models.notification import Notification  # noqa
from app.models.annotation import (  # noqa
    AnnotationBatch,
    AnnotationBatchAgent,
    AnnotationBatchPaper,
    AnnotationBatchAgentPaper,
    AnnotationBatchFact,
    AnnotationAssignment,
    AnnotationQuestion,
    AnnotationResponse,
    AnnotationPageState,
    CommentFact,
    CommentFactExtractionRun,
)
