from dataclasses import dataclass, field


class DockerSandboxPolicyError(ValueError):
    pass


@dataclass(frozen=True)
class DockerResourceLimits:
    memory: str = "256m"
    memory_swap: str = "256m"
    cpus: str = "0.5"
    pids_limit: int = 64
    nofile: str = "256:256"


@dataclass(frozen=True)
class DockerMount:
    source: str
    target: str
    readonly: bool = True


@dataclass(frozen=True)
class SecretReference:
    name: str
    credential_ref: str


@dataclass(frozen=True)
class ScriptTemplateInvocation:
    image_ref: str
    entrypoint: str
    argv: list[str]
    secrets: list[SecretReference] = field(default_factory=list)


@dataclass(frozen=True)
class DockerSandboxPolicy:
    network_mode: str = "none"
    read_only: bool = True
    tmpfs: str = "/tmp:rw,nosuid,nodev,size=64m"
    user: str = "10000:10000"
    cap_drop: list[str] = field(default_factory=lambda: ["ALL"])
    cap_add: list[str] = field(default_factory=list)
    security_opt: list[str] = field(default_factory=lambda: ["no-new-privileges=true"])
    privileged: bool = False
    mounts: list[DockerMount] = field(default_factory=list)
    resource_limits: DockerResourceLimits = field(default_factory=DockerResourceLimits)


SENSITIVE_MOUNT_FRAGMENTS = (
    "/var/run/docker.sock",
    "\\var\\run\\docker.sock",
    ".ssh",
    "/.ssh",
    "\\.ssh",
    "/root",
    "\\root",
    "/users/administrator",
    "\\users\\administrator",
    "/programdata/docker",
    "\\programdata\\docker",
    ".kube",
    "/.kube",
    "\\.kube",
    ".aws",
    "/.aws",
    "\\.aws",
    ".azure",
    "/.azure",
    "\\.azure",
)


def build_docker_run_command(
    invocation: ScriptTemplateInvocation,
    policy: DockerSandboxPolicy,
) -> list[str]:
    validate_policy(policy)

    command = [
        "docker",
        "run",
        "--rm",
        f"--network={policy.network_mode}",
    ]

    if policy.read_only:
        command.append("--read-only")

    command.extend(
        [
            "--tmpfs",
            policy.tmpfs,
            "--user",
            policy.user,
            *[f"--cap-drop={capability}" for capability in policy.cap_drop],
            *[
                option
                for security_opt in policy.security_opt
                for option in ("--security-opt", security_opt)
            ],
            f"--pids-limit={policy.resource_limits.pids_limit}",
            f"--memory={policy.resource_limits.memory}",
            f"--memory-swap={policy.resource_limits.memory_swap}",
            f"--cpus={policy.resource_limits.cpus}",
            "--ulimit",
            f"nofile={policy.resource_limits.nofile}",
        ]
    )

    for mount in policy.mounts:
        readonly_suffix = ",readonly" if mount.readonly else ""
        command.extend(
            [
                "--mount",
                f"type=bind,source={mount.source},target={mount.target}{readonly_suffix}",
            ]
        )

    command.extend(["--entrypoint", invocation.entrypoint, invocation.image_ref, *invocation.argv])
    return command


def validate_policy(policy: DockerSandboxPolicy) -> None:
    if policy.privileged:
        raise DockerSandboxPolicyError("privileged containers are forbidden")
    if policy.network_mode != "none" and not policy.network_mode.startswith("aegis-egress-"):
        raise DockerSandboxPolicyError("shell runner network must be none or an Aegis egress proxy")
    if policy.user.split(":", maxsplit=1)[0] == "0":
        raise DockerSandboxPolicyError("root containers are forbidden")
    if policy.cap_drop != ["ALL"]:
        raise DockerSandboxPolicyError("all linux capabilities must be dropped")
    if policy.cap_add:
        raise DockerSandboxPolicyError("adding linux capabilities is forbidden")
    if "no-new-privileges=true" not in policy.security_opt:
        raise DockerSandboxPolicyError("no-new-privileges security option is required")
    if policy.resource_limits.pids_limit <= 0:
        raise DockerSandboxPolicyError("pids limit must be positive")
    if policy.resource_limits.memory in {"0", "0m", "0Mi", "unlimited"}:
        raise DockerSandboxPolicyError("memory limit is required")

    for mount in policy.mounts:
        validate_mount(mount)


def validate_mount(mount: DockerMount) -> None:
    normalized_source = mount.source.replace("\\", "/").lower()
    if not mount.readonly:
        raise DockerSandboxPolicyError("bind mounts must be read-only by default")
    if any(fragment in normalized_source for fragment in SENSITIVE_MOUNT_FRAGMENTS):
        raise DockerSandboxPolicyError("sensitive host paths cannot be mounted")
    if not normalized_source.startswith("d:/projects/runtime/shell-runs/"):
        raise DockerSandboxPolicyError("mounts must stay inside the shell-run workspace")


def build_shell_command_preview(invocation: ScriptTemplateInvocation) -> str:
    rendered = " ".join([invocation.entrypoint, *invocation.argv])
    for secret in invocation.secrets:
        rendered = rendered.replace(f"${{{secret.name}}}", f"<secret:{secret.credential_ref}>")
        rendered = rendered.replace(secret.name, "<secret-name>")
    return rendered
