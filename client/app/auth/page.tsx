"use client";

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Button, LayerCard, Text } from "@cloudflare/kumo";
import { GithubLogoIcon, GoogleLogoIcon, WaveformIcon, WarningIcon } from "@phosphor-icons/react";
import { signIn } from "@/lib/auth-client";

type Provider = "github" | "google";

function AuthCard() {
  const searchParams = useSearchParams();
  const callbackURL = searchParams.get("callbackURL") || "/dashboard";
  const [pending, setPending] = useState<Provider | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleSignIn = async (provider: Provider) => {
    setPending(provider);
    setError(null);
    try {
      const { error } = await signIn.social({ provider, callbackURL });
      if (error) {
        setError(
          typeof error.message === "string" ? error.message : "Sign in failed. Please try again.",
        );
        setPending(null);
      }
      // On success Better Auth redirects to callbackURL.
    } catch {
      setError("Sign in failed. Please try again.");
      setPending(null);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-kumo-canvas px-4">
      <LayerCard className="w-full max-w-sm px-5 py-4 shadow-md ring ring-kumo-line">
        <div className="grid gap-6">
          <div className="grid gap-1.5">
            <div className="flex items-center gap-2">
              <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-kumo-brand">
                <WaveformIcon className="text-white" size={18} aria-hidden />
              </span>
              <Text as="h1" variant="heading">
                Sign in to Flow
              </Text>
            </div>
            <Text variant="secondary">
              Continue with a connected account to access your workspace.
            </Text>
          </div>

          {error && (
            <div
              role="alert"
              className="flex items-start gap-2 rounded-lg bg-kumo-danger-tint/70 p-4"
            >
              <span className="h-lh flex items-center">
                <WarningIcon weight="fill" className="fill-kumo-danger" aria-hidden />
              </span>
              <Text variant="error">{error}</Text>
            </div>
          )}

          <div className="grid gap-2">
            <Button
              variant="primary"
              className="w-full"
              icon={<GithubLogoIcon aria-hidden />}
              loading={pending === "github"}
              disabled={pending !== null}
              onClick={() => handleSignIn("github")}
            >
              Continue with GitHub
            </Button>
            <Button
              variant="secondary"
              className="w-full"
              icon={<GoogleLogoIcon aria-hidden />}
              loading={pending === "google"}
              disabled={pending !== null}
              onClick={() => handleSignIn("google")}
            >
              Continue with Google
            </Button>
          </div>

          <Text variant="secondary">
            Protected by secure session cookies. Only GitHub and Google accounts are accepted.
          </Text>
        </div>
      </LayerCard>
    </div>
  );
}

export default function AuthPage() {
  return (
    <Suspense>
      <AuthCard />
    </Suspense>
  );
}
