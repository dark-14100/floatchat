import { NextRequest, NextResponse } from "next/server";

const AUTH_PUBLIC_ROUTES = [
  "/login",
  "/signup",
  "/forgot-password",
  "/reset-password",
];

function isAuthPublicRoute(pathname: string): boolean {
  return AUTH_PUBLIC_ROUTES.some(
    (route) => pathname === route || pathname.startsWith(`${route}/`),
  );
}

function isStaticAsset(pathname: string): boolean {
  return /\.[^/]+$/.test(pathname);
}

export function middleware(request: NextRequest) {
  const { pathname, search } = request.nextUrl;

  if (pathname.startsWith("/_next") || pathname === "/favicon.ico" || isStaticAsset(pathname)) {
    return NextResponse.next();
  }

  const isAuthRoute = isAuthPublicRoute(pathname);
  const hasRefreshCookie = Boolean(request.cookies.get("floatchat_refresh")?.value);

  if (hasRefreshCookie && isAuthRoute) {
    return NextResponse.redirect(new URL("/chat", request.url));
  }

  if (!hasRefreshCookie && !isAuthRoute) {
    const loginUrl = new URL("/login", request.url);
    const redirectTarget = `${pathname}${search}`;
    loginUrl.searchParams.set("redirect", redirectTarget);
    return NextResponse.redirect(loginUrl);
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
