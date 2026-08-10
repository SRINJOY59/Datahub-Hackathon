"""Builds the GraphQL schema from the query and mutation roots."""
from __future__ import annotations

import strawberry

from api.resolvers import Mutation, Query

schema = strawberry.Schema(query=Query, mutation=Mutation)
