type FastApiDetail =
  | string
  | { code?: string; message?: string; msg?: string }
  | { msg?: string }[]
  | unknown;

export function extractApiErrorMessage(
  body: { detail?: FastApiDetail } | undefined,
  fallback: string,
): string {
  const detail = body?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    const joined = detail
      .map((d) => (typeof d === 'object' && d && 'msg' in d ? String(d.msg ?? '') : ''))
      .filter(Boolean)
      .join(', ');
    if (joined) return joined;
  }
  if (typeof detail === 'object' && detail !== null && 'message' in detail) {
    const m = (detail as { message?: unknown }).message;
    if (typeof m === 'string') return m;
  }
  return fallback;
}

export function getApiErrorCode(body: { detail?: FastApiDetail } | undefined): string | null {
  const detail = body?.detail;
  if (typeof detail === 'object' && detail !== null && !Array.isArray(detail) && 'code' in detail) {
    const code = (detail as { code?: unknown }).code;
    if (typeof code === 'string') return code;
  }
  return null;
}
