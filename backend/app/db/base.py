from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


from backend.app.iam import models as _iam_models  # noqa: E402, F401
