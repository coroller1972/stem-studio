import type { SVGProps } from "react";

export function StemMark(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 32 32" aria-hidden="true" {...props}>
      <path d="M5 19v-6M10 24V8M16 28V4M22 23V9M27 19v-6" />
    </svg>
  );
}

