import { revalidatePath, revalidateTag } from "next/cache";
import type { NextRequest } from "next/server";

// Pair documented by Next.js as "complementary primitives often used together":
// revalidatePath busts the rendered page HTML; revalidateTag busts the shared
// fetches. Both are needed for dynamic routes — tag alone leaves the page HTML
// fresh in OpenNext's S3 cache.
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
  const slug = (body as { slug?: unknown })?.slug;
  if (typeof appid !== "number" || !Number.isInteger(appid) || appid <= 0) {
    return Response.json({ ok: false, error: "bad_appid" }, { status: 400 });
  }
  if (typeof slug !== "string" || slug.length === 0) {
    return Response.json({ ok: false, error: "bad_slug" }, { status: 400 });
  }

  revalidatePath(`/games/${appid}/${slug}`);
  revalidateTag(`game-${appid}`, "max");
  return Response.json({ ok: true, appid, slug, now: Date.now() });
}
