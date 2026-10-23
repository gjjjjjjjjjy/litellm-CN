import { Logo } from "@/components/molecules/logo/Logo";
import { vendorName } from "./qosData";

export default function VendorName({ vendor }: { readonly vendor: string }) {
  const name = vendorName(vendor);
  return (
    <span className="flex min-w-0 items-center gap-1.5">
      <Logo provider={vendor} label={name} className="size-4 shrink-0" />
      <span className="truncate font-medium">{name}</span>
    </span>
  );
}
