import Link from "next/link";

import { Wordmark } from "@/components/brand/wordmark";

export default function NotFound() {
  return (
    <main id="main" className="mx-auto flex min-h-[70dvh] max-w-xl flex-col items-start justify-center gap-6 px-(--gutter)">
      <Wordmark />
      <h1 className="font-display text-display-sm leading-(--leading-tight)">This page isn&apos;t in the network.</h1>
      <Link href="/" className="text-sm text-vital underline underline-offset-4">
        Back to home
      </Link>
    </main>
  );
}
