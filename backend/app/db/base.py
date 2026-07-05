from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


from backend.app.audit import models as _audit_models  # noqa: E402, F401
from backend.app.execution import models as _execution_models  # noqa: E402, F401
from backend.app.iam import models as _iam_models  # noqa: E402, F401
from backend.app.knowledge import models as _knowledge_models  # noqa: E402, F401
from backend.app.model_gateway import models as _model_gateway_models  # noqa: E402, F401
from backend.app.observability import models as _observability_models  # noqa: E402, F401
from backend.app.policy_center import models as _policy_center_models  # noqa: E402, F401
from backend.app.policy_gate import models as _policy_gate_models  # noqa: E402, F401
from backend.app.runtime_approvals import models as _runtime_approvals_models  # noqa: E402, F401
from backend.app.tool_gateway import models as _tool_gateway_models  # noqa: E402, F401
from backend.app.tool_registry import models as _tool_registry_models  # noqa: E402, F401
from backend.app.workflow_runtime import models as _workflow_runtime_models  # noqa: E402, F401
from backend.app.workflows import models as _workflow_models  # noqa: E402, F401
