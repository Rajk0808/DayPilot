"""FastAPI application factory for DayPilot's HTTP boundary."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from daypilot.api.routes.goals import router as goals_router
from daypilot.api.routes.tasks import router as tasks_router
from daypilot.persistence.exceptions import EntityNotFoundError


def create_app(
    persistent_application=None,
    *,
    state_id: str | None = None,
    planning_window_provider=None,
) -> FastAPI:
    """Build the API with optional injectable service and planner context.

    Without injected values, runtime dependencies are read lazily from
    ``DATABASE_URL``, ``DAYPILOT_STATE_ID`` and the planning-window variables.
    """
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        engine = getattr(app.state, "database_engine", None)
        if engine is not None:
            engine.dispose()

    app = FastAPI(title="DayPilot API", version="0.1.0", lifespan=lifespan)
    app.state.persistent_application = persistent_application
    app.state.state_id = state_id
    app.state.planning_window_provider = planning_window_provider

    app.include_router(tasks_router)
    app.include_router(goals_router)

    @app.exception_handler(EntityNotFoundError)
    async def not_found_handler(_request: Request, exc: EntityNotFoundError):
        return JSONResponse(
            status_code=404,
            content={"detail": str(exc)},
        )

    @app.exception_handler(ValueError)
    async def validation_error_handler(_request: Request, exc: ValueError):
        return JSONResponse(
            status_code=422,
            content={"detail": str(exc)},
        )

    return app


app = create_app()
