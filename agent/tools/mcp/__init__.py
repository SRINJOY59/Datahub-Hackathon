"""DataHub Model Context Protocol integration.

Lets Sentinel read DataHub through the official `mcp-server-datahub` — the same
server Claude Desktop and Cursor use — rather than only the Python SDK. Kept in
its own package because it is a protocol integration (a subprocess + an stdio
session), not a graph query helper.
"""
