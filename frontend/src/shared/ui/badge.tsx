import * as React from "react";

import { cn } from "@/shared/lib/cn";

function Badge({ className, ...props }: React.ComponentProps<"span">) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full bg-white/80 px-2.5 py-1 text-xs font-medium text-ink shadow-sm",
        className,
      )}
      {...props}
    />
  );
}

export { Badge };
