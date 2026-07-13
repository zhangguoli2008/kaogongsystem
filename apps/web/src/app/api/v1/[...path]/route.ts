import { proxyApiRequest } from "@/lib/api-proxy";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type Context = { params: Promise<{ path: string[] }> };

async function handler(request: Request, context: Context) {
  const { path } = await context.params;
  return proxyApiRequest(request, path);
}

export {
  handler as DELETE,
  handler as GET,
  handler as HEAD,
  handler as OPTIONS,
  handler as PATCH,
  handler as POST,
  handler as PUT,
};
