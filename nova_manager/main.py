from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError

from nova_manager.core.exceptions import (
    RequestValidationException,
    ValidationException,
    create_exception_response,
)
from nova_manager.core.log import configure_logging
from nova_manager.middlewares.exceptions import ExceptionMiddleware

# Import event listeners to register them with SQLAlchemy
# import nova_manager.components.users.event_listeners  # noqa: F401
import nova_manager.components.user_experience.event_listeners  # noqa: F401

from nova_manager.api.auth.router import router as auth_router
from nova_manager.api.feature_flags.router import router as feature_flags_router
from nova_manager.api.segments.router import router as segments_router
from nova_manager.api.experiences.router import router as experiences_router
from nova_manager.api.user_experience.router import router as user_experience_router
from nova_manager.api.users.router import router as users_router
from nova_manager.api.metrics.router import router as metrics_router
from nova_manager.api.personalisations.router import router as personalisations_router
from nova_manager.api.recommendations.router import router as recommendations_router
from nova_manager.api.invitations.router import router as invitations_router
from nova_manager.api.playground.router import router as playground_router


configure_logging()
app = FastAPI()


# Mount static files
app.mount("/static", StaticFiles(directory="nova_manager/static"), name="static")


# Include Routers
app.include_router(auth_router, prefix="/api/v1/auth")
app.include_router(feature_flags_router, prefix="/api/v1/feature-flags")
app.include_router(segments_router, prefix="/api/v1/segments")
app.include_router(experiences_router, prefix="/api/v1/experiences")
app.include_router(user_experience_router, prefix="/api/v1/user-experience")
app.include_router(users_router, prefix="/api/v1/users")
app.include_router(metrics_router, prefix="/api/v1/metrics")
app.include_router(personalisations_router, prefix="/api/v1/personalisations")
app.include_router(recommendations_router, prefix="/api/v1/recommendations")
app.include_router(invitations_router, prefix="/api/v1/invitations")
app.include_router(playground_router, prefix="/api/v1/playground")


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return create_exception_response(RequestValidationException(exc.errors()))


@app.exception_handler(ValidationError)
async def pydantic_validation_exception_handler(request: Request, exc: ValidationError):
    return create_exception_response(ValidationException(exc.errors()))


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(ExceptionMiddleware)
