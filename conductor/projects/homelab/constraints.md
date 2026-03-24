# Project Constraints — maistro-engine

## Language & Runtime

- Python 3.12+
- Use `from __future__ import annotations` in all files
- Type hints required on all public functions

## Dependencies

- FastAPI for API endpoints
- Pydantic AI for agent framework
- structlog for logging
- pytest + pytest-asyncio for tests

## Code Style

- Ruff with line-length 100
- Follow existing patterns in the codebase
- Minimal comments — code should be self-documenting
- No docstrings on private methods unless complex

## Testing

- All new code must have tests
- Use pytest-asyncio with `asyncio_mode = "auto"`
- Test files go in `tests/` directory
- Use `MAISTRO_DRY_RUN=1` for tests that would call LLMs

## Architecture

- Source code in `src/maistro/`
- Agents in `src/maistro/agents/`
- Config in `src/maistro/config/`
- Tasks in `src/maistro/tasks/`
