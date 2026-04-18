import type { ReactNode } from "react";

import { Dialog, DialogContent, DialogDescription, DialogTitle } from "./primitives";

interface ConfirmDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  description: ReactNode;
  cancelLabel: ReactNode;
  confirmLabel: ReactNode;
  onCancel?: () => void;
  onConfirm: () => void;
}

export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  cancelLabel,
  confirmLabel,
  onCancel,
  onConfirm,
}: ConfirmDialogProps) {
  function handleCancel() {
    if (onCancel) {
      onCancel();
      return;
    }

    onOpenChange(false);
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="w-[calc(100%-2.5rem)] max-w-[380px] rounded-[28px] border-none bg-white px-7 pb-7 pt-7 sm:rounded-[28px] [&>button]:hidden">
        <DialogTitle className="text-left text-[20px] font-semibold tracking-[-0.02em] text-ink">
          {title}
        </DialogTitle>
        <DialogDescription className="mt-4 text-left text-[15px] leading-7 text-muted-foreground">
          {description}
        </DialogDescription>

        <div className="mt-8 flex items-center justify-end gap-8">
          <button
            type="button"
            className="text-[16px] font-medium text-muted-foreground"
            onClick={handleCancel}
          >
            {cancelLabel}
          </button>
          <button type="button" className="text-[16px] font-semibold text-ink" onClick={onConfirm}>
            {confirmLabel}
          </button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
