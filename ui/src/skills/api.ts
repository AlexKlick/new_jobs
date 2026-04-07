import type { SkillFile, SkillVersion } from './types';

const API_BASE = '/api/skills';

/**
 * List all skill files. Gracefully returns an empty list if the /api/skills
 * endpoint is not implemented on the backend — avoids an uncaught
 * "Unexpected token '<' (HTML 404 page instead of JSON)" error.
 */
export async function listSkills(): Promise<SkillFile[]> {
  try {
    const res = await fetch(`${API_BASE}`);
    if (!res.ok) {
      // 404/5xx means the endpoint isn't wired up yet; degrade gracefully
      if (res.status >= 400 && res.status < 500) {
        return [];
      }
      throw new Error(`Failed to list skills: ${res.statusText}`);
    }
    const data = await res.json();
    return data.skills ?? [];
  } catch (err) {
    // Network error or malformed JSON (e.g. backend returns HTML 404)
    if (err instanceof SyntaxError && err.message.includes('Unexpected token')) {
      return [];  // endpoint not implemented — degrade gracefully
    }
    throw err;
  }
}

export async function getSkill(filename: string): Promise<{ content: string; name: string }> {
  const res = await fetch(`${API_BASE}/${encodeURIComponent(filename)}`);
  if (!res.ok) throw new Error(`Failed to get skill: ${res.statusText}`);
  const text = await res.text();
  try {
    return JSON.parse(text);
  } catch {
    throw new Error(`Invalid JSON from /api/skills — is the backend wired up?`);
  }
}

export async function saveSkill(
  filename: string,
  content: string
): Promise<{ status: 'saved'; backup: string | null }> {
  const res = await fetch(`${API_BASE}/${encodeURIComponent(filename)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'text/plain' },
    body: content,
  });
  if (!res.ok) throw new Error(`Failed to save skill: ${res.statusText}`);
  return res.json();
}

export async function getSkillVersions(filename: string): Promise<SkillVersion[]> {
  const res = await fetch(`${API_BASE}/${encodeURIComponent(filename)}/versions`);
  if (!res.ok) throw new Error(`Failed to get versions: ${res.statusText}`);
  const data = await res.json();
  return data.versions ?? [];
}

export async function getSkillVersionContent(
  filename: string,
  versionName: string
): Promise<{ content: string; name: string }> {
  const res = await fetch(
    `${API_BASE}/${encodeURIComponent(filename)}/content/${encodeURIComponent(versionName)}`
  );
  if (!res.ok) throw new Error(`Failed to get version content: ${res.statusText}`);
  return res.json();
}
