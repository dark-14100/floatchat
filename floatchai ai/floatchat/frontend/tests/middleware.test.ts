import { describe, expect, it } from "vitest";
import { NextRequest } from "next/server";
import { middleware } from "@/middleware";

describe("frontend middleware", () => {
  it("allows unauthenticated protected route access for client-side auth bootstrap", () => {
    const request = new NextRequest("http://localhost/chat");

    const response = middleware(request);

    expect(response.headers.get("x-middleware-next")).toBe("1");
  });

  it("redirects authenticated users away from /login to /chat", () => {
    const request = new NextRequest("http://localhost/login", {
      headers: {
        cookie: "floatchat_refresh=abc123",
      },
    });

    const response = middleware(request);

    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe("http://localhost/chat");
  });

  it("allows unauthenticated users to access auth routes", () => {
    const request = new NextRequest("http://localhost/signup");

    const response = middleware(request);

    expect(response.headers.get("x-middleware-next")).toBe("1");
  });

  it("allows static/internal assets to pass through", () => {
    const request = new NextRequest("http://localhost/favicon.ico");

    const response = middleware(request);

    expect(response.headers.get("x-middleware-next")).toBe("1");
  });
});
