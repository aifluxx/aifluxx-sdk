import type { Agent, Version } from "../types";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function isUuid(value: unknown): value is string {
  return typeof value === "string" && UUID.test(value.trim());
}

function text(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

/** Turn GET /api/dev/agents into rows the run console can select. */
export function normalizeAgents(data: unknown): Agent[] {
  const rows = Array.isArray(data)
    ? data
    : data && typeof data === "object" && Array.isArray((data as { agents?: unknown }).agents)
      ? (data as { agents: unknown[] }).agents
      : [];
  return rows.flatMap((row) => {
    const agent = normalizeAgent(row);
    return agent ? [agent] : [];
  });
}

function normalizeAgent(row: unknown): Agent | null {
  if (!row || typeof row !== "object") return null;
  const raw = row as Record<string, unknown>;
  const slug = text(raw.slug);
  if (!slug) return null;
  const currentLabel = text(raw.version);
  const currentStatus = text(raw.state) || text(raw.status);
  const currentId = isUuid(raw.version_id) ? raw.version_id.trim() : isUuid(raw.versionId) ? raw.versionId.trim() : "";
  const versions: Version[] = [];
  const listed = Array.isArray(raw.versions) ? raw.versions : [];
  for (const item of listed) {
    if (!item || typeof item !== "object") continue;
    const version = item as Record<string, unknown>;
    const label = text(version.version) || text(version.label);
    const ownId = isUuid(version.version_id)
      ? version.version_id.trim()
      : isUuid(version.versionId)
        ? version.versionId.trim()
        : isUuid(version.id)
          ? version.id.trim()
          : "";
    const id = ownId || (currentId && label === currentLabel ? currentId : "");
    if (!id) continue;
    versions.push({
      id,
      version: label || currentLabel || id,
      status: text(version.status) || text(version.state) || (label === currentLabel ? currentStatus : ""),
      created_at: text(version.created_at) || undefined,
    });
  }
  if (currentId && !versions.some((version) => version.id === currentId)) {
    versions.unshift({
      id: currentId,
      version: currentLabel || currentId,
      status: currentStatus,
      created_at: text(raw.created_at) || text(raw.updated_at) || undefined,
    });
  }
  return {
    slug,
    name: text(raw.name) || undefined,
    category: text(raw.category) || undefined,
    versions,
  };
}
