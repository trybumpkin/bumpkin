from __future__ import annotations

from bumpkin.integrations.github.persistence_postgres_approval_ops import (
    PostgresApprovalOpsMixin,
)
from bumpkin.integrations.github.persistence_postgres_audit_ops import (
    PostgresAuditOpsMixin,
)
from bumpkin.integrations.github.persistence_postgres_base import (
    PostgresConnectionMixin,
)
from bumpkin.integrations.github.persistence_postgres_event_ops import (
    PostgresEventOpsMixin,
)
from bumpkin.integrations.github.persistence_postgres_publish_decision_ops import (
    PostgresPublishDecisionOpsMixin,
)
from bumpkin.integrations.github.persistence_postgres_publish_decision_query_ops import (
    PostgresPublishDecisionQueryOpsMixin,
)
from bumpkin.integrations.github.persistence_postgres_recommendation_ops import (
    PostgresRecommendationOpsMixin,
)
from bumpkin.integrations.github.persistence_postgres_release_backlog_ops import (
    PostgresReleaseBacklogOpsMixin,
)


class PostgresAppStateStore(
    PostgresConnectionMixin,
    PostgresEventOpsMixin,
    PostgresRecommendationOpsMixin,
    PostgresReleaseBacklogOpsMixin,
    PostgresApprovalOpsMixin,
    PostgresPublishDecisionOpsMixin,
    PostgresPublishDecisionQueryOpsMixin,
    PostgresAuditOpsMixin,
):
    pass
