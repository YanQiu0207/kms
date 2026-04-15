import { computed, reactive, readonly } from "vue";

import { getUiSettings } from "@/api/client";
import type { UiLocaleMode } from "@/types/observability";
import { renderLocale, translateUiText, type UiTextKey } from "@/utils/i18n";

type LocalePreferenceSource = "backend" | "user";

interface UiLocaleState {
  started: boolean;
  mode: UiLocaleMode;
  backendDefault: UiLocaleMode;
  source: LocalePreferenceSource;
  availableLocales: readonly UiLocaleMode[];
}

const STORAGE_KEY = "obs-local.ui-locale";
const FALLBACK_MODE: UiLocaleMode = "bilingual";

const state = reactive<UiLocaleState>({
  started: false,
  mode: FALLBACK_MODE,
  backendDefault: FALLBACK_MODE,
  source: "backend",
  availableLocales: ["zh", "en", "bilingual"],
});

let startPromise: Promise<void> | null = null;

function isLocaleMode(value: string | null): value is UiLocaleMode {
  return value === "zh" || value === "en" || value === "bilingual";
}

function readStoredLocale(): UiLocaleMode | null {
  const raw = window.localStorage.getItem(STORAGE_KEY);
  return isLocaleMode(raw) ? raw : null;
}

function writeStoredLocale(mode: UiLocaleMode | null): void {
  if (mode === null) {
    window.localStorage.removeItem(STORAGE_KEY);
    return;
  }
  window.localStorage.setItem(STORAGE_KEY, mode);
}

async function start(): Promise<void> {
  if (state.started) {
    return;
  }
  if (startPromise) {
    return startPromise;
  }
  startPromise = (async () => {
    try {
      const settings = await getUiSettings();
      state.backendDefault = settings.default_locale;
      state.availableLocales = settings.available_locales;
    } catch {
      state.backendDefault = FALLBACK_MODE;
      state.availableLocales = ["zh", "en", "bilingual"];
    }

    const storedLocale = readStoredLocale();
    if (storedLocale) {
      state.mode = storedLocale;
      state.source = "user";
    } else {
      state.mode = state.backendDefault;
      state.source = "backend";
    }
    state.started = true;
  })();
  try {
    await startPromise;
  } finally {
    startPromise = null;
  }
}

function setMode(mode: UiLocaleMode): void {
  state.mode = mode;
  state.source = "user";
  writeStoredLocale(mode);
}

function resetMode(): void {
  state.mode = state.backendDefault;
  state.source = "backend";
  writeStoredLocale(null);
}

export function useUiLocaleStore() {
  return {
    state: readonly(state),
    mode: computed(() => state.mode),
    start,
    setMode,
    resetMode,
    t: (key: UiTextKey) => translateUiText(state.mode, key),
    pair: (zh: string, en: string) => renderLocale(state.mode, zh, en),
  };
}
