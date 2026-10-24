// ============================================================
// Utility helpers
// ============================================================

/**
 * structuredContent must be a JSON object: the SDK refuses a tools/call result
 * whose structuredContent is an array or null ("expected record"). A list the
 * backend returns comes back as { items }, a bare value as { value }, nothing as {}.
 */
export function toStructured(data: unknown): { [key: string]: unknown } {
  if (Array.isArray(data)) return { items: data };
  if (data === null || data === undefined) return {};
  if (typeof data === "object") return data as { [key: string]: unknown };
  return { value: data };
}
