from backend.app.core.settings import AppSettings
from backend.app.main import create_app
from fastapi.testclient import TestClient


def test_create_app_sets_openapi_metadata() -> None:
    app = create_app()

    assert app.title == "AegisFlow API"
    assert app.version == "0.1.0"


def test_create_app_does_not_setup_workflow_checkpoints_by_default() -> None:
    lifecycle = RecordingCheckpointLifecycle()
    app = create_app(checkpoint_lifecycle=lifecycle)

    with TestClient(app):
        pass

    assert lifecycle.setup_calls == 0


def test_create_app_sets_up_workflow_checkpoints_when_enabled() -> None:
    lifecycle = RecordingCheckpointLifecycle()
    settings = AppSettings(workflow_checkpoint_setup_on_startup=True)
    app = create_app(settings, checkpoint_lifecycle=lifecycle)

    with TestClient(app):
        pass

    assert lifecycle.setup_calls == 1


class RecordingCheckpointLifecycle:
    def __init__(self) -> None:
        self.setup_calls = 0

    async def setup(self) -> None:
        self.setup_calls += 1
