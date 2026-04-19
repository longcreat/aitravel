import * as React from "react";

import { cn } from "@/shared/lib/cn";

import { Input } from "./input";

interface FlatingInputProps extends Omit<React.ComponentProps<"input">, "placeholder"> {
  label: string;
  containerClassName?: string;
  labelPositionerClassName?: string;
  labelClassName?: string;
}

function hasInputValue(value: React.ComponentProps<"input">["value"] | undefined) {
  if (value == null) {
    return false;
  }

  if (Array.isArray(value)) {
    return value.length > 0;
  }

  return String(value).length > 0;
}

const FlatingInput = React.forwardRef<HTMLInputElement, FlatingInputProps>(
  (
    {
      className,
      containerClassName,
      defaultValue,
      id,
      label,
      labelClassName,
      labelPositionerClassName,
      onBlur,
      onChange,
      onFocus,
      type,
      value,
      ...props
    },
    ref,
  ) => {
    const generatedId = React.useId();
    const inputId = id ?? generatedId;
    const [isFocused, setIsFocused] = React.useState(false);
    const [hasUncontrolledValue, setHasUncontrolledValue] = React.useState(hasInputValue(defaultValue));
    const isControlled = value !== undefined;
    const shouldFloat = isFocused || (isControlled ? hasInputValue(value) : hasUncontrolledValue);

    function handleFocus(event: React.FocusEvent<HTMLInputElement>) {
      setIsFocused(true);
      onFocus?.(event);
    }

    function handleBlur(event: React.FocusEvent<HTMLInputElement>) {
      setIsFocused(false);
      if (!isControlled) {
        setHasUncontrolledValue(event.target.value.length > 0);
      }
      onBlur?.(event);
    }

    function handleChange(event: React.ChangeEvent<HTMLInputElement>) {
      if (!isControlled) {
        setHasUncontrolledValue(event.target.value.length > 0);
      }
      onChange?.(event);
    }

    return (
      <div
        className={cn("relative", containerClassName)}
        data-floating={shouldFloat ? "true" : "false"}
        data-focused={isFocused ? "true" : "false"}
      >
        <Input
          {...props}
          ref={ref}
          id={inputId}
          type={type}
          value={value}
          defaultValue={defaultValue}
          placeholder=" "
          onBlur={handleBlur}
          onChange={handleChange}
          onFocus={handleFocus}
          className={cn(
            "peer placeholder:text-transparent focus-visible:border-ring focus-visible:ring-0 focus-visible:ring-offset-0",
            className,
          )}
        />
        <label
          htmlFor={inputId}
          className={cn(
            "pointer-events-none absolute left-4 z-10 transition-all duration-200 ease-out",
            shouldFloat ? "top-0 -translate-y-1/2" : "top-1/2 -translate-y-1/2",
            labelPositionerClassName,
          )}
        >
          <div
            className={cn(
              "rounded-sm px-1.5 transition-colors duration-200",
              shouldFloat ? "bg-background" : "bg-transparent",
              labelClassName,
            )}
          >
            <span
              className={cn(
                "block leading-none transition-all duration-200 ease-out",
                shouldFloat ? "text-[13px] font-medium" : "text-[16px] font-normal",
                isFocused ? "text-ring" : shouldFloat ? "text-ink" : "text-muted-foreground",
              )}
            >
              {label}
            </span>
          </div>
        </label>
      </div>
    );
  },
);
FlatingInput.displayName = "FlatingInput";

export { FlatingInput };
