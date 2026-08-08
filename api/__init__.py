"""The dashboard's read API.

Where agent/ decides and acts, this package only reads: it turns the incident
store and the action journal into a GraphQL schema a web dashboard can query.
It has no write path and no opinion about remediation — a separate top-level
package because "what happened, queryable" is a different concern from "the
loop that makes it happen", the same way ml/, governance/ and ingestion/ sit
beside agent/ rather than inside it.
"""
