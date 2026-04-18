import { ChevronRight, MapPinned } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { getLocationPermissionSummary } from "@/features/location/lib/location-permission";
import { PageBackButton, SettingsGroup, SettingsRowButton } from "@/shared/ui";

export function ProfilePermissionsPage() {
  const navigate = useNavigate();
  const locationPermissionSummary = getLocationPermissionSummary();

  function handleBack() {
    if (window.history.length > 1) {
      navigate(-1);
      return;
    }

    navigate("/profile", { replace: true });
  }

  return (
    <div className="flex h-full w-full flex-col overflow-y-auto bg-[#faf9f7]">
      <div className="flex items-center px-6 pt-[calc(0.9rem+env(safe-area-inset-top))]">
        <PageBackButton ariaLabel="back-profile-permissions" onClick={handleBack} />
      </div>

      <section className="px-4 pb-8 pt-6">
        <SettingsGroup>
          <SettingsRowButton
            aria-label="open-location-permission"
            align="start"
            icon={
              <div className="rounded-full bg-[#f4ebd9] p-2 text-[#d4704e]">
                <MapPinned className="h-4 w-4" />
              </div>
            }
            title="定位"
            description="允许应用在需要时读取你的位置，用于本地推荐和上下文提示。"
            trailing={
              <div className="flex items-center gap-2 text-sm text-[#809b9f]">
                <span>{locationPermissionSummary}</span>
                <ChevronRight className="h-4 w-4" />
              </div>
            }
            onClick={() => navigate("/profile/permissions/location")}
          />
        </SettingsGroup>
      </section>
    </div>
  );
}
