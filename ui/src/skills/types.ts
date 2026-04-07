export interface SkillFile {
  name: string;
  modified: number;
  size: number;
}

export interface SkillVersion {
  name: string;
  modified: number;
  current: boolean;
}

export interface SkillListResponse {
  skills: SkillFile[];
}

export interface SkillResponse {
  content: string;
  name: string;
}

export interface VersionsResponse {
  versions: SkillVersion[];
}

export interface SaveResponse {
  status: "saved";
  backup: string | null;
}

export interface ValidationResult {
  valid: boolean;
  errors: Array<{ line: number; message: string }>;
}
