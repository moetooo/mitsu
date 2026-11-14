// FE-18: one guarded boundary for browser storage.
//
// Every write used to be a bare `localStorage.setItem`. localStorage throws on a
// full quota (and in private modes on Safari), so a single oversized write turned
// into an unhandled exception in an effect — the app kept rendering but nothing
// was saved, silently, forever. Reads were partially guarded and partially not.
//
// Policy: reads always return the caller's fallback, writes report success and
// warn once per session. Nothing here ever throws to a render path.

let warned = false;

export function warnStorageOnce(error) {
  if (warned) return;
  warned = true;
  const name = error && error.name ? error.name : 'error';
  console.warn(
    `[mitsu] Browser storage is unavailable or full (${name}). ` +
      'Settings and saved titles will not persist in this tab.'
  );
}

// Test seam: the warn-once flag is module state.
export function resetStorageWarning() {
  warned = false;
}

// Accepts one key or a list of keys; the legacy `mangamind_*` names are tried
// after the current ones so an upgrade keeps the user's data.
export function readJSON(keys, fallback) {
  const list = Array.isArray(keys) ? keys : [keys];
  for (const key of list) {
    let raw;
    try {
      raw = localStorage.getItem(key);
    } catch (error) {
      warnStorageOnce(error);
      return fallback;
    }
    if (raw === null || raw === undefined) continue;
    try {
      const parsed = JSON.parse(raw);
      if (parsed !== null && parsed !== undefined) return parsed;
    } catch (error) {
      // A corrupted value must not poison the app: fall through, and the caller
      // gets its default. The bad value is left in place so it can be inspected.
      warnStorageOnce(error);
    }
  }
  return fallback;
}

export function writeJSON(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
    return true;
  } catch (error) {
    warnStorageOnce(error);
    return false;
  }
}

export function removeKey(key) {
  try {
    localStorage.removeItem(key);
    return true;
  } catch (error) {
    warnStorageOnce(error);
    return false;
  }
}
