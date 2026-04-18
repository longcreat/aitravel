import { type HTMLAttributes, type ReactNode, useEffect, useId } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";

import { useAppSurfaceOverlayRoot } from "@/shared/layouts/app-surface-overlay";
import { cn } from "@/shared/lib/cn";

interface AppSurfaceSheetProps {
  open: boolean;
  onClose: () => void;
  title?: ReactNode;
  description?: ReactNode;
  children: ReactNode;
  className?: string;
  titleClassName?: string;
  descriptionClassName?: string;
  closeButtonClassName?: string;
  closeLabel?: string;
  contentProps?: HTMLAttributes<HTMLDivElement>;
}

export function AppSurfaceSheet({
  open,
  onClose,
  title,
  description,
  children,
  className,
  titleClassName,
  descriptionClassName,
  closeButtonClassName,
  closeLabel = "close-sheet",
  contentProps,
}: AppSurfaceSheetProps) {
  const overlayRoot = useAppSurfaceOverlayRoot();
  const titleId = useId();
  const descriptionId = useId();

  useEffect(() => {
    if (!open) {
      return;
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        onClose();
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [onClose, open]);

  if (!open || !overlayRoot) {
    return null;
  }

  return createPortal(
    <div className="absolute inset-0 z-50 pointer-events-auto">
      <button
        type="button"
        aria-label={`${closeLabel}-overlay`}
        className="absolute inset-0 bg-black/80"
        onClick={onClose}
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={title ? titleId : undefined}
        aria-describedby={description ? descriptionId : undefined}
        className={cn(
          "absolute inset-x-4 bottom-4 rounded-[28px] bg-white px-6 pb-6 pt-6 shadow-xl",
          className,
        )}
        {...contentProps}
      >
        <button
          type="button"
          aria-label={closeLabel}
          className={cn(
            "absolute right-4 top-4 inline-flex h-8 w-8 items-center justify-center rounded-full text-[#8a857b] transition-colors hover:bg-[#f3efe7] hover:text-[#5f5a52]",
            closeButtonClassName,
          )}
          onClick={onClose}
        >
          <X className="h-4 w-4" />
        </button>

        {title ? (
          <div id={titleId} className={cn("text-center font-serif text-[20px] font-semibold tracking-[-0.02em] text-[#2c2b28]", titleClassName)}>
            {title}
          </div>
        ) : null}
        {description ? (
          <div
            id={descriptionId}
            className={cn("mt-4 text-center text-[15px] leading-8 text-muted-foreground", descriptionClassName)}
          >
            {description}
          </div>
        ) : null}
        <div className={title || description ? "mt-5" : ""}>{children}</div>
      </div>
    </div>,
    overlayRoot,
  );
}
