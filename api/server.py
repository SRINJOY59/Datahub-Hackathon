"""Mounts the GraphQL schema onto a FastAPI app.

Two ways to run this:

  * attached to the webhook server (`python -m agent serve`), so one process
    and one port serves both inbound triggers and the dashboard's reads;
  * standalone (`python -m api`), for dashboard development when webhooks
    aren't configured and there is nothing to trigger.

CORS is permissive by default because the dashboard is, for now, a local dev
server on a different port. Tighten `allow_origins` before this leaves a
laptop.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from strawberry.fastapi import GraphQLRouter

from api.actions_routes import router as actions_router
from api.advisory_routes import router as advisory_router
from api.chat_routes import router as chat_router
from api.schema import schema

GRAPHQL_PATH = "/graphql"


def attach(app: FastAPI) -> None:
    """Mount GraphQL (with the GraphiQL explorer), chat, actuation, and advisory routes."""
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(GraphQLRouter(schema), prefix=GRAPHQL_PATH)
    app.include_router(chat_router)
    app.include_router(actions_router)
    app.include_router(advisory_router)


def create_app() -> FastAPI:
    """A standalone app for running the API without the webhook server.

    Built lazily by api/__main__.py, not at import time — attach() alone is
    what agent/__main__.py needs, and importing it should not have the side
    effect of constructing a second, unused FastAPI app.
    """
    app = FastAPI(title="Sentinel Dashboard API", version="0.1.0")
    attach(app)
    return app
