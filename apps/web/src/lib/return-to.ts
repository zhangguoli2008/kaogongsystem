export const DEFAULT_RETURN_TO = "/dashboard";

const publicPaths = new Set(["/login", "/register"]);

export function resolveReturnTo(value: string | null | undefined): string {
  if (!value || !value.startsWith("/") || value.startsWith("//") || value.includes("\\")) {
    return DEFAULT_RETURN_TO;
  }

  const pathname = value.split(/[?#]/, 1)[0];
  return publicPaths.has(pathname) ? DEFAULT_RETURN_TO : value;
}

export function loginPathFor(pathname: string | null, search: string): string {
  const currentPath = `${pathname ?? DEFAULT_RETURN_TO}${search ? `?${search}` : ""}`;
  return `/login?returnTo=${encodeURIComponent(resolveReturnTo(currentPath))}`;
}
