import { FIRM_LOGOS, firmInitials } from "@/lib/brand";

/** A firm's logo if it has one, otherwise a monogram of its initials. */
export default function FirmMark({ name, slug, className = "h-10 w-10 text-base" }: {
  name: string; slug?: string; className?: string;
}) {
  const logo = slug ? FIRM_LOGOS[slug] : undefined;
  if (logo) {
    return <img src={logo} alt="" className={`${className} shrink-0 rounded-md bg-white object-cover object-left ring-1 ring-white/20`} />;
  }
  return (
    <span aria-hidden className={`${className} flex shrink-0 items-center justify-center rounded-md bg-gold font-display font-bold text-navy`}>
      {firmInitials(name)}
    </span>
  );
}
