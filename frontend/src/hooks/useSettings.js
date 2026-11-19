import { useCallback, useEffect, useState } from 'react';
import { readJSON, writeJSON } from '../utils/storage';
import { normalizeSettings, PAGE_SIZE } from '../utils/settings';

/**
 * UI preferences: the one owner of the settings blob (FE-29 extraction, FE-18,
 * FE-22).
 *
 * Reads guarded and normalised, so a corrupted or hand-edited blob cannot put an
 * unknown theme or an unknown grid size into the DOM. The page size is not a
 * setting any more: it is `PAGE_SIZE`, one number for every grid and one page
 * per Load More click.
 * Every writer goes through the same normaliser, including the settings modal and
 * the preset buttons, so state never holds an unvalidated value.
 *
 * The DOM attributes and the storage write live here too: they are consequences
 * of `settings`, and having them in the component is what made two places own
 * one value.
 */
export const SETTINGS_KEYS = ['mitsu_settings', 'mangamind_settings'];

export function applySettingsAttributes(settings) {
  const root = document.documentElement;
  root.setAttribute('data-theme', settings?.theme || 'washi');
  root.setAttribute('data-title-font', settings?.fontStyle || 'serif');
  root.setAttribute('data-accent', settings?.accent || settings?.hoverAccent || 'rose');
}

export default function useSettings() {
  const [settings, setSettings] = useState(() =>
    normalizeSettings(readJSON(SETTINGS_KEYS, null))
  );

  const updateSettings = useCallback((updater) => {
    setSettings(prev =>
      normalizeSettings(typeof updater === 'function' ? updater(prev) : updater)
    );
  }, []);

  useEffect(() => {
    applySettingsAttributes(settings);
    if (settings) writeJSON('mitsu_settings', settings);
  }, [settings]);

  // The page size is a constant, not a preference: see PAGE_SIZE.
  const requestLimit = PAGE_SIZE;

  return { settings, updateSettings, requestLimit };
}
