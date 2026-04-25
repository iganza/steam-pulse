import { revalidateTag } from "next/cache";
import type { NextRequest } from "next/server";

// 'max' = stale served while a fresh fetch fills the cache in the background.
export async function POST(req: NextRequest) {
  const expectedToken = process.env.REVALIDATE_TOKEN;
  if (!expectedToken) {
    return Response.json(
      { ok: false, error: "revalidate_token_unconfigured" },
      { status: 500 },
    );
  }
  if (req.headers.get("x-revalidate-token") !== expectedToken) {
    return Response.json({ ok: false, error: "unauthorized" }, { status: 401 });
  }

  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return Response.json({ ok: false, error: "bad_json" }, { status: 400 });
  }

  const appid = (body as { appid?: unknown })?.appid;
  if (typeof appid !== "number" || !Number.isInteger(appid) || appid <= 0) {
    return Response.json({ ok: false, error: "bad_appid" }, { status: 400 });
  }

  revalidateTag(`game-${appid}`, "max");
  return Response.json({ ok: true, appid, now: Date.now() });
}
