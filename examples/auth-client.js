export function createAuthClient({ baseUrl, storage = localStorage, fetchImpl = fetch }) {
  let refreshInFlight;
  let authQueue = Promise.resolve();
  const accessKey = "taskhub_access_token";

  function enqueueAuth(operation) {
    const result = authQueue.then(operation, operation);
    authQueue = result.catch(() => {});
    return result;
  }

  async function refresh() {
    if (!refreshInFlight) {
      refreshInFlight = enqueueAuth(async () => {
        const response = await fetchImpl(`${baseUrl}/auth/refresh`, {
          method: "POST",
          credentials: "include",
        });
        if (!response.ok) {
          storage.removeItem(accessKey);
          throw new Error("Session expired");
        }
        const { access_token } = await response.json();
        storage.setItem(accessKey, access_token);
        return access_token;
      })
        .finally(() => { refreshInFlight = undefined; });
    }
    return refreshInFlight;
  }

  return {
    async login(email, password) {
      return enqueueAuth(async () => {
        const response = await fetchImpl(`${baseUrl}/auth/login`, {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email, password }),
        });
        if (!response.ok) throw new Error("Login failed");
        const { access_token } = await response.json();
        storage.setItem(accessKey, access_token);
      });
    },
    async request(path, options = {}) {
      if (!path.startsWith("/") || path.startsWith("//")) throw new Error("Expected an API path");
      const url = new URL(`${baseUrl}${path}`, baseUrl);
      if (url.origin !== new URL(baseUrl).origin) throw new Error("Expected same-origin API path");
      const send = () => {
        const headers = new Headers(options.headers);
        const accessToken = storage.getItem(accessKey);
        if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
        return fetchImpl(url.toString(), { ...options, credentials: "include", headers });
      };
      let response = await send();
      if (response.status === 401 && !path.startsWith("/auth/")) {
        await refresh();
        response = await send();
      }
      return response;
    },
    async logout() {
      return enqueueAuth(async () => {
        try {
          const response = await fetchImpl(`${baseUrl}/auth/logout`, {
            method: "POST",
            credentials: "include",
          });
          if (!response.ok) throw new Error("Logout failed");
        } finally {
          storage.removeItem(accessKey);
        }
      });
    },
  };
}
