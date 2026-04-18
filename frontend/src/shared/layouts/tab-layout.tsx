import { Outlet } from "react-router-dom";
import { AuthGateModal } from "@/features/auth/ui/auth-gate-modal";
import { MobileShell } from "@/shared/layouts/mobile-shell";

export function TabLayout() {
  return (
    <MobileShell>
      <div className="flex min-h-0 w-full flex-1 flex-col overflow-hidden">
        <Outlet />
      </div>
      <AuthGateModal />
    </MobileShell>
  );
}
