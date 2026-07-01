from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )


class Account(Base, TimestampMixin):
    __tablename__ = "accounts"
    __table_args__ = (UniqueConstraint("email", name="uq_accounts_email"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    is_super_admin: Mapped[bool] = mapped_column(default=False, nullable=False)

    memberships: Mapped[list["ProjectMember"]] = relationship(back_populates="account")


class Project(Base, TimestampMixin):
    __tablename__ = "projects"
    __table_args__ = (UniqueConstraint("slug", name="uq_projects_slug"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")

    members: Mapped[list["ProjectMember"]] = relationship(back_populates="project")
    roles: Mapped[list["ProjectRole"]] = relationship(back_populates="project")


class ProjectMember(Base, TimestampMixin):
    __tablename__ = "project_members"
    __table_args__ = (
        UniqueConstraint("project_id", "account_id", name="uq_project_members_project_account"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    account_id: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")

    account: Mapped[Account] = relationship(back_populates="memberships")
    project: Mapped[Project] = relationship(back_populates="members")
    role_bindings: Mapped[list["ProjectMemberRole"]] = relationship(back_populates="member")


class ProjectRole(Base, TimestampMixin):
    __tablename__ = "project_roles"
    __table_args__ = (UniqueConstraint("project_id", "code", name="uq_project_roles_project_code"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")

    project: Mapped[Project] = relationship(back_populates="roles")
    permission_bindings: Mapped[list["ProjectRolePermission"]] = relationship(back_populates="role")
    member_bindings: Mapped[list["ProjectMemberRole"]] = relationship(back_populates="role")


class ProjectPermission(Base):
    __tablename__ = "project_permissions"
    __table_args__ = (UniqueConstraint("code", name="uq_project_permissions_code"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    role_bindings: Mapped[list["ProjectRolePermission"]] = relationship(back_populates="permission")


class ProjectRolePermission(Base):
    __tablename__ = "project_role_permissions"

    role_id: Mapped[UUID] = mapped_column(ForeignKey("project_roles.id"), primary_key=True)
    permission_id: Mapped[UUID] = mapped_column(
        ForeignKey("project_permissions.id"),
        primary_key=True,
    )

    role: Mapped[ProjectRole] = relationship(back_populates="permission_bindings")
    permission: Mapped[ProjectPermission] = relationship(back_populates="role_bindings")


class ProjectMemberRole(Base):
    __tablename__ = "project_member_roles"

    member_id: Mapped[UUID] = mapped_column(ForeignKey("project_members.id"), primary_key=True)
    role_id: Mapped[UUID] = mapped_column(ForeignKey("project_roles.id"), primary_key=True)

    member: Mapped[ProjectMember] = relationship(back_populates="role_bindings")
    role: Mapped[ProjectRole] = relationship(back_populates="member_bindings")
