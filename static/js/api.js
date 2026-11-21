// One fetch wrapper for every API call: JSON in/out, timeouts and friendly error messages.

/**
 * @param {string} path API path, e.g. "/api/air?lat=..."
 * @param {{method?: string, body?: object, timeout?: number}} [options]
 */
export async function api(path, { method = 'GET', body, timeout = 60000 } = {}) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeout);
  try {
    const res = await fetch(path, {
      method,
      headers: body ? { 'Content-Type': 'application/json' } : {},
      body: body ? JSON.stringify(body) : undefined,
      signal: ctrl.signal,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      let msg = `Something went wrong (${res.status}). Please try again.`;
      if (typeof data.detail === 'string') msg = data.detail;
      else if (res.status === 422) msg = 'Some details look invalid. Please check and try again.';
      throw new Error(msg);
    }
    return data;
  } catch (err) {
    if (err.name === 'AbortError') throw new Error('This is taking too long. Please try again.');
    if (err instanceof TypeError) throw new Error('Could not reach SmogSafe. Check your internet connection.');
    throw err;
  } finally {
    clearTimeout(timer);
  }
}
