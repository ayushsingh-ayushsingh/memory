// app/webtop/page.tsx
"use client";

export default function WebtopPage() {
  return (
    <main className="h-screen w-full flex">
      <iframe
        src="https://32.199.184.0/"
        title="Debian KDE Webtop"
        className="h-full w-full border-0"
        allow="clipboard-read; clipboard-write; fullscreen"
        allowFullScreen
      />
    </main>
  );
}
