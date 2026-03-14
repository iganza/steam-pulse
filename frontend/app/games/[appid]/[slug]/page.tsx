import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getPreview } from "@/lib/api";
import { ApiError } from "@/lib/api";
import { GameReportClient } from "./GameReportClient";

interface Props {
  params: Promise<{ appid: string; slug: string }>;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { appid } = await params;
  try {
    const preview = await getPreview(Number(appid));
    return {
      title: preview.game_name,
      description: preview.one_liner,
      openGraph: {
        title: `${preview.game_name} — Player Intelligence Report`,
        description: preview.one_liner,
      },
    };
  } catch {
    return { title: "Game Report" };
  }
}

export default async function GameReportPage({ params }: Props) {
  const { appid } = await params;
  const numericAppid = Number(appid);

  if (!numericAppid || isNaN(numericAppid)) notFound();

  let preview;
  try {
    preview = await getPreview(numericAppid);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) notFound();
    // Network errors: render without preview rather than hard-failing
    if (err instanceof ApiError) {
      preview = null;
    } else {
      throw err;
    }
  }

  // These would come from /api/games/{appid} in production;
  // preview is all we need for SSR hydration of the client component.
  return (
    <GameReportClient
      preview={preview}
      appid={numericAppid}
      headerImage={undefined}
      releaseDate={undefined}
      developer={undefined}
      priceUsd={undefined}
      isFree={false}
      genres={[]}
    />
  );
}

// ISR: revalidate every hour, new appids render on-demand
export const revalidate = 3600;
