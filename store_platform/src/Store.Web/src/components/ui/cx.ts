/** Tiny className joiner — drops falsy parts. Keeps primitives dependency-free. */
export function cx(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(' ');
}
