/**
 * Client-side checks for instant feedback. They mirror apps/api/app/core/validation.py;
 * the API remains the authority and its field errors are always shown too.
 */

export const DEMO_VERIFICATION_DISCLAIMER =
  "Demo verification only. The last 4 digits of your mobile number are used for prototype verification instead of a real OTP.";

export const PASSWORD_MIN = 10;

const EMAIL =
  /^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$/;
const NAME = /^\p{L}(?:\p{L}|[ .'-])*$/u;
const PIN = /^[1-9][0-9]{5}$/;

/** Returns the 10 national digits, or null. Accepts +91 / 91 / 0 prefixes, spaces, dashes. */
export function indianMobileDigits(value: string): string | null {
  let d = value.trim().replace(/[\s\-()]/g, "");
  if (d.startsWith("+91")) d = d.slice(3);
  else if (d.length === 12 && d.startsWith("91")) d = d.slice(2);
  else if (d.length === 11 && d.startsWith("0")) d = d.slice(1);
  return /^[6-9][0-9]{9}$/.test(d) ? d : null;
}

export type Validator = (value: string) => string | null;

export const validators = {
  full_name: (v: string) => {
    const name = v.trim().replace(/\s+/g, " ");
    const letters = [...name].filter((c) => /\p{L}/u.test(c)).length;
    return name.length >= 2 && name.length <= 120 && letters >= 2 && NAME.test(name)
      ? null
      : "Enter your full name using letters, spaces, . ' or -";
  },
  email: (v: string) => (EMAIL.test(v.trim()) ? null : "Enter a valid email address"),
  mobile: (v: string) =>
    indianMobileDigits(v) ? null : "Enter a valid 10-digit Indian mobile number",
  blood_group: (v: string) => (v ? null : "Select your blood group"),
  address: (v: string) => {
    const n = v.trim().length;
    return n >= 5 && n <= 255 ? null : "Address must be between 5 and 255 characters";
  },
  city: (v: string) => (v.trim().length >= 2 ? null : "Enter a valid city name"),
  state: (v: string) => (v ? null : "Select your state or union territory"),
  pin_code: (v: string) =>
    PIN.test(v.replace(/\s/g, "")) ? null : "Enter a valid 6-digit PIN code",
  password: (v: string) =>
    v.length >= PASSWORD_MIN && v.length <= 128
      ? null
      : `Password must be ${PASSWORD_MIN}-128 characters`,
} satisfies Record<string, Validator>;

export type FieldName = keyof typeof validators;

export function validate<K extends FieldName>(
  values: Record<K, string>,
  fields: readonly K[],
): Partial<Record<K, string>> {
  const errors: Partial<Record<K, string>> = {};
  for (const field of fields) {
    const message = validators[field](values[field] ?? "");
    if (message) errors[field] = message;
  }
  return errors;
}

/** A light, honest strength hint (length-driven; no fake entropy maths). */
export function passwordStrength(v: string): { score: 0 | 1 | 2 | 3; label: string } {
  if (v.length < PASSWORD_MIN) return { score: 0, label: `At least ${PASSWORD_MIN} characters` };
  const kinds = [/[a-z]/, /[A-Z]/, /[0-9]/, /[^A-Za-z0-9]/].filter((r) => r.test(v)).length;
  if (v.length >= 16 || (v.length >= 12 && kinds >= 3)) return { score: 3, label: "Strong" };
  if (v.length >= 12 || kinds >= 3) return { score: 2, label: "Good" };
  return { score: 1, label: "Fair — longer is stronger" };
}
