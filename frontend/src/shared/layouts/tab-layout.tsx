import { NavLink, Outlet } from "react-router-dom";
import { MessageSquare, User } from "lucide-react";
import { MobileShell } from "@/shared/layouts/mobile-shell";

export function TabLayout() {
  return (
    <MobileShell>
      <div className="flex flex-1 flex-col overflow-hidden w-full min-h-0">
        <Outlet />
      </div>
      {/* Bottom Tab Bar */}
      <nav className="flex h-[60px] shrink-0 items-center bg-paper/95 backdrop-blur-md pb-[env(safe-area-inset-bottom)] z-20 border-t border-black/[0.03]">
        <NavLink
          to="/"
          className={({ isActive }) =>
            `flex flex-1 flex-col items-center justify-center gap-1 transition-colors ${
              isActive ? "text-[#d4704e]" : "text-[#a29f98] hover:text-[#d4704e]/80"
            }`
          }
        >
          <MessageSquare className="h-[22px] w-[22px]" />
          <span className="text-[10px] font-medium leading-none mt-0.5">对话</span>
        </NavLink>
        <NavLink
          to="/profile"
          className={({ isActive }) =>
            `flex flex-1 flex-col items-center justify-center gap-1 transition-colors ${
              isActive ? "text-[#d4704e]" : "text-[#a29f98] hover:text-[#d4704e]/80"
            }`
          }
        >
          <User className="h-[22px] w-[22px]" />
          <span className="text-[10px] font-medium leading-none mt-0.5">我的</span>
        </NavLink>
      </nav>
    </MobileShell>
  );
}
