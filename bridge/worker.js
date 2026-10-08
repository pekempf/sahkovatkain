// Cloudflare Worker: private Shelly settings relay.
// Bind a KV namespace named SETTINGS and configure secrets:
// SHELLY_WRITE_TOKEN and GITHUB_READ_TOKEN (different random values).
// Public repo contains no credentials.
const allowed = ["porssi", "porssi-1", "porssi-2", "porssi-3"];
const reply = (data, status = 200) => new Response(JSON.stringify(data), {
  status, headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" }
});
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname !== "/settings") return reply({ error: "not_found" }, 404);
    const token = request.headers.get("authorization") || "";
    if (request.method === "POST") {
      if (!env.SHELLY_WRITE_TOKEN || token !== "Bearer " + env.SHELLY_WRITE_TOKEN)
        return reply({ error: "unauthorized" }, 401);
      let body;
      try { body = await request.json(); } catch { return reply({ error: "bad_json" }, 400); }
      if (!body || typeof body !== "object" || Array.isArray(body) ||
          Object.keys(body).sort().join(",") !== [...allowed].sort().join(","))
        return reply({ error: "wrong_keys" }, 400);
      for (const key of allowed) {
        if (!body[key] || typeof body[key] !== "object" || Array.isArray(body[key]))
          return reply({ error: "invalid_value", key }, 400);
      }
      const snapshot = { received_at: new Date().toISOString(), settings: body };
      await env.SETTINGS.put("current", JSON.stringify(snapshot));
      return reply({ ok: true, received_at: snapshot.received_at });
    }
    if (request.method === "GET") {
      if (!env.GITHUB_READ_TOKEN || token !== "Bearer " + env.GITHUB_READ_TOKEN)
        return reply({ error: "unauthorized" }, 401);
      const value = await env.SETTINGS.get("current");
      return value ? new Response(value, { headers: {
        "content-type": "application/json", "cache-control": "no-store"
      }}) : reply({ error: "no_settings_yet" }, 404);
    }
    return reply({ error: "method_not_allowed" }, 405);
  }
};
