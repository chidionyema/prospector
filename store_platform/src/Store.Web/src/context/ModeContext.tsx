import React, { createContext, useCallback, useContext, useState } from 'react';

/**
 * WR-036 (Model C): the active role is a PRESENTATION MODE, not a security boundary. One account is
 * dual-capable (it can both fund introductions and earn them), but presents exactly one active role at
 * a time. Mode lives only in the client (localStorage); the server NEVER trusts it. Ownership and the
 * self-dealing block are enforced server-side regardless of what mode the browser is in, so this is
 * purely which surface we emphasise (nav, dashboard hero, creation defaults), never what you may do.
 */
export type Mode = 'seeker' | 'connector';

const STORAGE_KEY = 'tie.mode';

interface ModeContextType {
  /** The active presentation mode. Defaults to 'seeker' (the seeker-led primary actor, WR-031). */
  mode: Mode;
  /** Switch mode and persist it as the last-used preference for this device. */
  setMode: (mode: Mode) => void;
}

const ModeContext = createContext<ModeContextType>({
  mode: 'seeker',
  setMode: () => {},
});

function isMode(value: string | null): value is Mode {
  return value === 'seeker' || value === 'connector';
}

/** Reads the persisted mode, SSR-safe (returns the default on the server where there is no storage). */
function readPersistedMode(): Mode {
  if (typeof window === 'undefined') return 'seeker';
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (isMode(stored)) return stored;
  } catch {
    // localStorage can throw (private mode / disabled storage); fall back to the default silently.
  }
  return 'seeker';
}

export function ModeProvider({ children }: { children: React.ReactNode }) {
  // Lazy initial read, not a post-mount effect: mode-dependent UI (the authed nav, the dashboard) only
  // renders after the async auth probe resolves on the client, so there is no SSR'd mode-dependent DOM
  // to mismatch against. This keeps the switch instant and avoids a cascading setState-in-effect.
  const [mode, setModeState] = useState<Mode>(readPersistedMode);

  const setMode = useCallback((next: Mode) => {
    setModeState(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Persist is best-effort; the in-memory switch still works for this session.
    }
  }, []);

  return <ModeContext.Provider value={{ mode, setMode }}>{children}</ModeContext.Provider>;
}

export const useMode = () => useContext(ModeContext);

/**
 * Seed the first-run mode from the role a user picks at onboarding (the only signal we have, since the
 * session `/me` carries no role). Buyer seeds seeker, Connector seeds connector. Safe to call before
 * the ModeProvider mounts elsewhere: it writes the same localStorage key the provider reads.
 */
export function seedModeFromRole(role: string) {
  const next: Mode = role === 'Connector' ? 'connector' : 'seeker';
  try {
    window.localStorage.setItem(STORAGE_KEY, next);
  } catch {
    // best-effort
  }
}
