import { beforeEach, describe, expect, it } from "vitest";
import { useAuthStore } from "@/store/authStore";

describe("authStore", () => {
  beforeEach(() => {
    useAuthStore.setState({
      currentUser: null,
      accessToken: null,
      isAuthenticated: false,
    });
  });

  it("setAuth stores user/token and authenticates", () => {
    useAuthStore.getState().setAuth(
      {
        user_id: "u-1",
        name: "Test User",
        email: "test@example.com",
        role: "researcher",
      },
      "token-abc",
    );

    const state = useAuthStore.getState();
    expect(state.currentUser?.user_id).toBe("u-1");
    expect(state.accessToken).toBe("token-abc");
    expect(state.isAuthenticated).toBe(true);
  });

  it("clearAuth resets all auth state", () => {
    useAuthStore.getState().setAuth(
      {
        user_id: "u-1",
        name: "Test User",
        email: "test@example.com",
        role: "researcher",
      },
      "token-abc",
    );

    useAuthStore.getState().clearAuth();

    const state = useAuthStore.getState();
    expect(state.currentUser).toBeNull();
    expect(state.accessToken).toBeNull();
    expect(state.isAuthenticated).toBe(false);
  });

  it("setAccessToken updates token while preserving auth status from user", () => {
    useAuthStore.getState().setAuth(
      {
        user_id: "u-2",
        name: "Another User",
        email: "another@example.com",
        role: "admin",
      },
      "token-old",
    );

    useAuthStore.getState().setAccessToken("token-new");

    const state = useAuthStore.getState();
    expect(state.accessToken).toBe("token-new");
    expect(state.isAuthenticated).toBe(true);
  });
});
