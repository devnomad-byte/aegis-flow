from backend.app.main import create_app


def test_create_app_sets_openapi_metadata() -> None:
    app = create_app()

    assert app.title == "AegisFlow API"
    assert app.version == "0.1.0"
