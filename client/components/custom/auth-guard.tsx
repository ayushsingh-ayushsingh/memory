"use client";

import type { ReactNode } from "react";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { Loader, Text } from "@cloudflare/kumo";
import { useSession } from "@/lib/auth-client";

/**
 * Client-side gate for protected sections. Middleware already redirects
 * cookie-less visitors; this covers the case where the cookie exists but
 * the session is expired or revoked.
 */
export function AuthGuard({ children }: { children: ReactNode }) {
  const { data, isPending } = useSession();
  const router = useRouter();

  useEffect(() => {
    if (!isPending && !data) {
      router.replace("/auth?callbackURL=%2Fdashboard");
    }
  }, [data, isPending, router]);

  if (isPending || !data) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-2 bg-kumo-canvas">
        <Loader />
        <Text variant="secondary">verifying</Text>
      </div>
    );
  }

  return <>{children}</>;
}
