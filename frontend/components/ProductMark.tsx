import Link from "next/link";
import { PRODUCT } from "@/lib/brand";

/** Advocatus wordmark for the public pages. `light` for use on navy. */
export default function ProductMark({ light = false, href = "/" }: { light?: boolean; href?: string }) {
  return (
    <Link href={href} className="inline-flex items-center gap-2" aria-label={`${PRODUCT.name} home`}>
      <span className="flex h-8 w-8 items-center justify-center rounded-md bg-gold font-display text-lg font-bold text-navy">
        A
      </span>
      <span className={`font-display text-xl font-bold tracking-tight ${light ? "text-white" : "text-navy"}`}>
        {PRODUCT.name}
      </span>
    </Link>
  );
}
