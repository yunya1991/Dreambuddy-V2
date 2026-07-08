type AuthRuntimeEnv = Partial<Record<"NEXTAUTH_URL" | "AUTH_URL" | "PORT" | "AUTH_TRUST_HOST", string>>;

function isLocalhostUrl(value: string) {
  try {
    const url = new URL(value);
    return url.hostname === "localhost" || url.hostname === "127.0.0.1";
  } catch {
    return false;
  }
}

function rewriteLocalUrlToPort(value: string, appPort: string) {
  const url = new URL(value);
  url.port = appPort;
  return url.toString().replace(/\/$/, "");
}

export function getAuthRuntimeOptions(env: AuthRuntimeEnv) {
  const configuredUrl = env.NEXTAUTH_URL || env.AUTH_URL || `http://localhost:${env.PORT || "3000"}`;
  const appPort = env.PORT || "3000";
  const baseUrl = isLocalhostUrl(configuredUrl)
    ? rewriteLocalUrlToPort(configuredUrl, appPort)
    : configuredUrl.replace(/\/$/, "");

  const trustHost = env.AUTH_TRUST_HOST === "true" || isLocalhostUrl(baseUrl);

  return {
    baseUrl,
    trustHost,
  };
}
