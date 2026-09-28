export type VeyraEnv = "dev" | "test" | "demo" | "production";

const KNOWN: readonly VeyraEnv[] = ["dev", "test", "demo", "production"];

/** Public (browser-safe) environment name. Unknown values fall back to "dev" (never "production"). */
export function publicEnv(raw: string | undefined = process.env.NEXT_PUBLIC_VEYRA_ENV): VeyraEnv {
  return KNOWN.includes(raw as VeyraEnv) ? (raw as VeyraEnv) : "dev";
}

export const isProductionEnv = (env: VeyraEnv = publicEnv()): boolean => env === "production";
