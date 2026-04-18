import { ArrowLeft } from "lucide-react";

import { cn } from "@/shared/lib/cn";

import { Button, type ButtonProps } from "./primitives";

interface PageBackButtonProps extends Omit<ButtonProps, "children" | "size" | "variant"> {
  ariaLabel: string;
  iconClassName?: string;
}

export function PageBackButton({
  ariaLabel,
  className,
  iconClassName,
  type = "button",
  ...props
}: PageBackButtonProps) {
  return (
    <Button
      type={type}
      size="icon"
      variant="ghost"
      aria-label={ariaLabel}
      className={cn("h-14 w-14 rounded-full bg-white shadow-sm hover:bg-secondary/50", className)}
      {...props}
    >
      <ArrowLeft className={cn("h-7 w-7 text-ink", iconClassName)} />
    </Button>
  );
}
