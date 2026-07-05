$ErrorActionPreference = "Stop"

function Invoke-Step {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Name,
        [Parameter(Mandatory = $true)]
        [scriptblock] $Command
    )

    Write-Host "[verify-backend] $Name"
    & $Command
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

Invoke-Step "ruff check" { uv run ruff check . }
Invoke-Step "ruff format check" { uv run ruff format --check . }
Invoke-Step "mypy" { uv run mypy . }
Invoke-Step "pytest" { uv run pytest }
Invoke-Step "pytest coverage" { uv run pytest --cov=backend.app --cov-report=term-missing }
Invoke-Step "alembic check" { uv run alembic check }
