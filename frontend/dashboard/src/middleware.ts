import { NextRequest, NextResponse } from "next/server";

function hasAuth0Config(): boolean {
  return Boolean(
    process.env.AUTH0_DOMAIN &&
      process.env.AUTH0_CLIENT_ID &&
      process.env.AUTH0_SECRET &&
      (process.env.AUTH0_CLIENT_SECRET ||
        process.env.AUTH0_CLIENT_ASSERTION_SIGNING_KEY),
  );
}

export async function middleware(request: NextRequest) {
  if (!hasAuth0Config()) {
    return NextResponse.next();
  }

  const { auth0 } = await import("./lib/auth0");
  const authRes = await auth0.middleware(request);

  // Auth routes — let Auth0 middleware handle them fully (login, callback, logout)
  if (request.nextUrl.pathname.startsWith("/auth")) {
    return authRes;
  }

  const { origin } = new URL(request.url);
  const session = await auth0.getSession(request);

  // No session → redirect to Auth0 login
  if (!session) {
    return NextResponse.redirect(`${origin}/auth/login`);
  }

  return authRes;
}

export const config = {
  matcher: [
    /*
     * Protect all routes except:
     * - _next/static  (static assets)
     * - _next/image   (image optimization)
     * - favicon.ico, etc.
     */
    "/((?!_next/static|_next/image|images|favicon\\.ico|$).*)",
  ],
};
