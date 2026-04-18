import * as React from "react";

import { cn } from "@/shared/lib/cn";

export function SettingsGroup({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("overflow-hidden rounded-2xl bg-white shadow-sm", className)} {...props} />;
}

interface SettingsRowBaseProps {
  icon?: React.ReactNode;
  title: React.ReactNode;
  description?: React.ReactNode;
  trailing?: React.ReactNode;
  bordered?: boolean;
  align?: "center" | "start";
  className?: string;
  titleClassName?: string;
  descriptionClassName?: string;
  interactive?: boolean;
}

function SettingsRowContent({
  icon,
  title,
  description,
  trailing,
  bordered = false,
  align = "center",
  className,
  titleClassName,
  descriptionClassName,
  interactive = false,
}: SettingsRowBaseProps) {
  return (
    <div
      className={cn(
        "flex w-full justify-between gap-3 px-4 py-4 text-left",
        align === "start" ? "items-start" : "items-center",
        bordered ? "border-b" : "",
        interactive ? "transition-colors hover:bg-black/5" : "",
        className,
      )}
    >
      <div className={cn("flex min-w-0 gap-3", align === "start" ? "items-start" : "items-center")}>
        {icon ? <div className="shrink-0">{icon}</div> : null}
        <div className="min-w-0 flex-1">
          <div className={cn("text-sm font-medium text-ink", titleClassName)}>{title}</div>
          {description ? (
            <p className={cn("mt-1 text-sm leading-7 text-[#809b9f]", descriptionClassName)}>{description}</p>
          ) : null}
        </div>
      </div>

      {trailing ? <div className={cn("shrink-0", align === "start" ? "pt-0.5" : "")}>{trailing}</div> : null}
    </div>
  );
}

export function SettingsRow({
  icon,
  title,
  description,
  trailing,
  bordered,
  align,
  className,
  titleClassName,
  descriptionClassName,
  interactive,
  ...props
}: SettingsRowBaseProps & React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div {...props}>
      <SettingsRowContent
        icon={icon}
        title={title}
        description={description}
        trailing={trailing}
        bordered={bordered}
        align={align}
        className={className}
        titleClassName={titleClassName}
        descriptionClassName={descriptionClassName}
        interactive={interactive}
      />
    </div>
  );
}

export function SettingsRowButton({
  icon,
  title,
  description,
  trailing,
  bordered,
  align,
  className,
  titleClassName,
  descriptionClassName,
  type = "button",
  ...props
}: SettingsRowBaseProps & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button type={type} className="block w-full" {...props}>
      <SettingsRowContent
        icon={icon}
        title={title}
        description={description}
        trailing={trailing}
        bordered={bordered}
        align={align}
        className={className}
        titleClassName={titleClassName}
        descriptionClassName={descriptionClassName}
        interactive
      />
    </button>
  );
}
