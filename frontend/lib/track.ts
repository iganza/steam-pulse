export function track(event: string, props: Record<string, unknown> = {}): void {
  if (process.env.NODE_ENV !== "production") {
    console.log(`[track] ${event}`, props);
  }
}
