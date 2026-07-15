from __future__ import annotations

from bumpkin.integrations.github.persistence_sqlite_approval_ops import (
    SqliteApprovalOpsMixin,
)
from bumpkin.integrations.github.persistence_sqlite_audit_ops import (
    SqliteAuditOpsMixin,
)
from bumpkin.integrations.github.persistence_sqlite_base import (
    SqliteConnectionMixin,
)
from bumpkin.integrations.github.persistence_sqlite_event_ops import (
    SqliteEventOpsMixin,
)
from bumpkin.integrations.github.persistence_sqlite_publish_decision_ops import (
    SqlitePublishDecisionOpsMixin,
)
from bumpkin.integrations.github.persistence_sqlite_publish_decision_query_ops import (
    SqlitePublishDecisionQueryOpsMixin,
)
from bumpkin.integrations.github.persistence_sqlite_recommendation_ops import (
    SqliteRecommendationOpsMixin,
)
from bumpkin.integrations.github.persistence_sqlite_release_backlog_ops import (
    SqliteReleaseBacklogOpsMixin,
)


class SqliteAppStateStore(
    SqliteConnectionMixin,
    SqliteEventOpsMixin,
    SqliteRecommendationOpsMixin,
    SqliteReleaseBacklogOpsMixin,
    SqliteApprovalOpsMixin,
    SqlitePublishDecisionOpsMixin,
    SqlitePublishDecisionQueryOpsMixin,
    SqliteAuditOpsMixin,
):
    pass
