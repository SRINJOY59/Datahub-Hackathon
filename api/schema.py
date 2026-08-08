"""Builds the GraphQL schema from the query root."""
from __future__ import annotations

import strawberry

from api.resolvers import Query

schema = strawberry.Schema(query=Query)
