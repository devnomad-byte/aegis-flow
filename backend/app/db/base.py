from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


from backend.app.audit import models as _audit_models  # noqa: E402, F401
from backend.app.iam import models as _iam_models  # noqa: E402, F401
from backend.app.tool_registry import models as _tool_registry_models  # noqa: E402, F401
from backend.app.workflows import models as _workflow_models  # noqa: E402, F401
