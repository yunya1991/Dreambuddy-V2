export function countBy(items: string[]): Record<string, number> {
  return items.reduce<Record<string, number>>((acc, item) => {
    if (!item) return acc;
    acc[item] = (acc[item] || 0) + 1;
    return acc;
  }, {});
}

export function stripMarkdown(input: string): string {
  return input
    .replace(/^#+\s+/gm, "")
    .replace(/[\r\n]+/g, " ")
    .replace(/\*+/g, "")
    .replace(/`[^`]*`/g, "")
    .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/<[^>]*>/g, "")
    .replace(/\|/g, " ")
    .replace(/-+/g, " ")
    .replace(/\s{2,}/g, " ")
    .trim();
}

export function normalizeArtifactId(rawId: string): string {
  if (rawId.includes("/")) {
    return rawId.split("/").pop() || rawId;
  }

  return rawId;
}

export function normalizeTags(rawTags: unknown): string[] {
  if (Array.isArray(rawTags)) {
    return rawTags.map((tag) => String(tag)).filter(Boolean);
  }

  if (typeof rawTags === "string") {
    return rawTags
      .split(/[,\s]+/)
      .map((tag) => tag.trim())
      .filter(Boolean);
  }

  return [];
}
