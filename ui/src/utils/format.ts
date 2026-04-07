/**
 * Centralized formatting utilities for the Job Application Tracker.
 * All display transformations for backend enum values should flow through these functions.
 */

// Known abbreviations that need special casing
const KNOWN_ABBREVIATIONS: Record<string, string> = {
  ATS: 'ATS',
  AI: 'AI',
  LLM: 'LLM',
  MCP: 'MCP',
  ID: 'ID',
  URL: 'URL',
};

// Known status values from ApplicationStatus and ExternalEvaluation.verdict
const STATUS_LABELS: Record<string, string> = {
  // Application status values
  COMPLETE: 'Complete',
  PARTIAL_RESUME: 'Partial Resume',
  MARKDOWN: 'Markdown',
  MISSING: 'Missing',
  // Evaluation verdict values
  NEEDS_REVISION: 'Needs Revision',
  APPROVED: 'Approved',
  PENDING: 'Pending',
};

/**
 * Transforms a backend enum status value to a human-readable Title Case label.
 * Unknown enum values pass through unchanged to prevent crashes on unrecognized input.
 */
export function formatStatusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status.replace(/_/g, ' ');
}

/**
 * Transforms a snake_case or camelCase key to a human-readable Title Case label.
 * Known abbreviations (ATS, AI, LLM, MCP, etc.) are properly cased.
 * Example: 'ats_keyword_coverage' -> 'ATS Keyword Coverage'
 */
export function formatLabel(key: string): string {
  const words = key.replace(/_/g, ' ').split(/\s+/);
  return words.map(word => {
    const upper = word.toUpperCase();
    return KNOWN_ABBREVIATIONS[upper] ?? word.charAt(0).toUpperCase() + word.slice(1).toLowerCase();
  }).join(' ');
}

/**
 * Abbreviates a salary range string for compact display.
 * Examples:
 *   '$170,000' -> '$170k'
 *   '$170,000–$200,000' -> '$170k–$200k'
 *   '$170,000 + equity' -> '$170k + equity'
 *   'Competitive' -> 'Competitive' (pass-through)
 */
export function formatSalary(salary: string | null | undefined): string {
  if (!salary) return '—';

  // Pass through non-numeric salary strings (e.g., "Competitive")
  if (!/\d/.test(salary)) return salary;

  // Regex to match salary patterns: numbers with commas/periods, ranges, and suffixes
  // Captures: (number with suffix) – (number with suffix)
  const rangeMatch = salary.match(/^([$€£]?\s*[\d,]+(?:\.\d+)?)\s*(?:–|[-])\s*([$€£]?\s*[\d,]+(?:\.\d+)?(?:\s*\+\s*.+)?)$/);
  
  if (rangeMatch) {
    const [, min, max] = rangeMatch;
    return `${abbreviateNumber(min)}–${abbreviateNumber(max)}`;
  }

  // Single number with potential suffix
  const suffixMatch = salary.match(/^([$€£]?\s*[\d,]+(?:\.\d+)?)\s*(.*)$/);
  if (suffixMatch) {
    const [, num, suffix] = suffixMatch;
    const abbreviated = abbreviateNumber(num);
    return suffix.trim() ? `${abbreviated} ${suffix.trim()}` : abbreviated;
  }

  return salary;
}

function abbreviateNumber(value: string): string {
  // Remove currency symbols and whitespace
  const cleaned = value.replace(/[$€£\s]/g, '');
  // Remove commas
  const noCommas = cleaned.replace(/,/g, '');
  
  const num = parseFloat(noCommas);
  if (isNaN(num)) return value;

  if (num >= 1_000_000) {
    return `${(num / 1_000_000).toFixed(1).replace(/\.0$/, '')}M`;
  }
  if (num >= 1_000) {
    return `${(num / 1_000).toFixed(0)}k`;
  }
  return noCommas;
}
