/**
 * FloatChat — Zustand Auth Store (Feature 13)
 *
 * Access token is memory-only. Never persisted to localStorage/sessionStorage.
 */

import { create } from "zustand";
import type { User } from "@/types/auth";

interface AuthStore {
  currentUser: User | null;
  accessToken: string | null;
  isAuthenticated: boolean;
  setAuth: (user: User, token: string) => void;
  clearAuth: () => void;
  setAccessToken: (token: string | null) => void;
}

export const useAuthStore = create<AuthStore>((set, get) => ({
  currentUser: null,
  accessToken: null,
  isAuthenticated: false,

  setAuth: (user, token) =>
    set({
      currentUser: user,
      accessToken: token,
      isAuthenticated: user !== null,
    }),

  clearAuth: () =>
    set({
      currentUser: null,
      accessToken: null,
      isAuthenticated: false,
    }),

  setAccessToken: (token) =>
    set({
      accessToken: token,
      isAuthenticated: get().currentUser !== null,
    }),
}));
