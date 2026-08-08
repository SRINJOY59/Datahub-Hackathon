// A thin fetch wrapper rather than a GraphQL client library. This app's
// query surface is small and fixed (a handful of resolvers over a local
// SQLite store), so urql/Apollo's cache normalization, dedup, and
// subscription plumbing would be paying for a scale problem this app
// doesn't have. If subscriptions or a larger query surface show up later,
// that's the point to revisit this call.

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8090";

export class GraphQLError extends Error {
  constructor(message: string, public errors: unknown[]) {
    super(message);
    this.name = "GraphQLError";
  }
}

export async function gql<T>(
  query: string,
  variables?: Record<string, unknown>,
  init?: RequestInit,
): Promise<T> {
  const res = await fetch(`${API_URL}/graphql`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, variables }),
    ...init,
  });

  if (!res.ok) {
    throw new GraphQLError(`GraphQL request failed: HTTP ${res.status}`, []);
  }

  const json = await res.json();
  if (json.errors?.length) {
    throw new GraphQLError(
      json.errors.map((e: { message: string }) => e.message).join("; "),
      json.errors,
    );
  }
  return json.data as T;
}

export { API_URL };
