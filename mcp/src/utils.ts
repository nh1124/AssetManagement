// ============================================================
// Utility helpers
// ============================================================

/** Cast any object to the index-signature type required by structuredContent */
export function toStructured(data: unknown): { [key: string]: unknown } {
  return data as unknown as { [key: string]: unknown };
}
