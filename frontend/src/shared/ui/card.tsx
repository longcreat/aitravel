import * as React from "react";

import { cn } from "@/shared/lib/cn";

function Card({ className, ...props }: React.ComponentProps<"div">) {
  return <div className={cn("rounded-card bg-paper shadow-float", className)} {...props} />;
}

function CardHeader({ className, ...props }: React.ComponentProps<"div">) {
  return <div className={cn("px-4 pt-4", className)} {...props} />;
}

function CardTitle({ className, ...props }: React.ComponentProps<"h3">) {
  return <h3 className={cn("font-display text-base font-bold", className)} {...props} />;
}

function CardContent({ className, ...props }: React.ComponentProps<"div">) {
  return <div className={cn("px-4 pb-4 pt-2", className)} {...props} />;
}

export { Card, CardHeader, CardTitle, CardContent };
