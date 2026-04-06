import * as React from "react";
import { cn } from "@/shared/lib/cn";

export interface MobileShellProps extends React.HTMLAttributes<HTMLDivElement> {
  children: React.ReactNode;
}

/**
 * MobileShell 布局容器
 * 强制约束内容区域在移动端尺寸 (max-width: 430px) 内显示居中
 * 去除了重复的 `.mobile-shell` 类，直接在此管理样式规则
 */
export function MobileShell({ children, className, ...props }: MobileShellProps) {
  return (
    <div className="flex min-h-dvh w-full items-center justify-center bg-gray-100 sm:py-4">
      <main
        className={cn(
          "relative flex h-dvh w-full max-w-[430px] flex-col overflow-hidden bg-shell shadow-2xl sm:h-[844px] sm:rounded-[40px] sm:border-[8px] sm:border-gray-900",
          className
        )}
        {...props}
      >
        <div className="travel-noise pointer-events-none absolute inset-0 z-0 opacity-40 mix-blend-overlay" />
        <div className="relative flex h-full flex-col z-10 w-full">
          {children}
        </div>
      </main>
    </div>
  );
}
