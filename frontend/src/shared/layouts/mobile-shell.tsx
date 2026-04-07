import * as React from "react";
import { cn } from "@/shared/lib/cn";

export interface MobileShellProps extends React.HTMLAttributes<HTMLDivElement> {
  children: React.ReactNode;
}

function StatusBarIcon() {
  return (
    <div className="flex items-end gap-[2px]">
      <span className="h-[5px] w-[2px] rounded-full bg-[#2c2b28]/80" />
      <span className="h-[7px] w-[2px] rounded-full bg-[#2c2b28]/80" />
      <span className="h-[9px] w-[2px] rounded-full bg-[#2c2b28]/80" />
      <span className="h-[11px] w-[2px] rounded-full bg-[#2c2b28]/80" />
    </div>
  );
}

function WifiIcon() {
  return (
    <div className="relative h-[12px] w-[14px]">
      <span className="absolute left-1/2 top-[7px] h-[3px] w-[3px] -translate-x-1/2 rounded-full bg-[#2c2b28]/80" />
      <span className="absolute left-1/2 top-[3px] h-[8px] w-[10px] -translate-x-1/2 rounded-t-full border-x border-t border-[#2c2b28]/80" />
    </div>
  );
}

function BatteryIcon() {
  return (
    <div className="flex items-center gap-[2px]">
      <div className="relative h-[11px] w-[21px] rounded-[4px] border border-[#2c2b28]/75 p-[1px]">
        <div className="h-full w-[72%] rounded-[2px] bg-[#2c2b28]/80" />
      </div>
      <span className="h-[5px] w-[2px] rounded-r-full bg-[#2c2b28]/60" />
    </div>
  );
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
          "relative flex h-dvh w-full max-w-[430px] flex-col overflow-hidden bg-shell sm:h-[844px] sm:rounded-[40px] sm:border-[8px] sm:border-[#d9dde3]",
          className
        )}
        {...props}
      >
        <div className="travel-noise pointer-events-none absolute inset-0 z-0 opacity-40 mix-blend-overlay" />
        <div className="pointer-events-none absolute inset-x-0 top-0 z-20 hidden sm:block">
          <div className="relative flex h-[34px] items-center justify-between px-6 pt-2 text-[13px] font-semibold text-[#2c2b28]">
            <span>9:41</span>
            <div className="flex items-center gap-1.5">
              <StatusBarIcon />
              <WifiIcon />
              <BatteryIcon />
            </div>
            <div className="absolute left-1/2 top-2 h-[26px] w-[108px] -translate-x-1/2 rounded-full bg-[#16181d]" />
          </div>
        </div>
        <div className="relative z-10 flex h-full w-full flex-col sm:pt-[34px]">
          {children}
        </div>
      </main>
    </div>
  );
}
