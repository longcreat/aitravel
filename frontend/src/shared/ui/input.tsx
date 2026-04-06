import * as React from "react";

import { cn } from "@/shared/lib/cn";

const Input = React.forwardRef<HTMLInputElement, React.ComponentProps<"input">>(({ className, ...props }, ref) => {
  return (
    <input
      ref={ref}
      className={cn(
        "h-11 w-full rounded-2xl bg-white/90 px-4 text-sm text-ink shadow-sm outline-none transition placeholder:text-[#5e7274] focus:ring-2 focus:ring-mint/20",
        className,
      )}
      {...props}
    />
  );
});
Input.displayName = "Input";

export { Input };
