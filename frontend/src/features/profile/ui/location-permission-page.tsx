import { useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  getStoredLocationPermission,
  setStoredLocationPermission,
} from "@/features/location/lib/location-permission";
import { PageBackButton, SettingsGroup, SettingsRow, Switch } from "@/shared/ui";

export function LocationPermissionPage() {
  const navigate = useNavigate();
  const [permission, setPermission] = useState(() => getStoredLocationPermission());
  const locationEnabled = permission === "enabled";

  function handleBack() {
    if (window.history.length > 1) {
      navigate(-1);
      return;
    }

    navigate("/profile/permissions", { replace: true });
  }

  function handlePermissionChange(checked: boolean) {
    const nextPermission = checked ? "enabled" : "disabled";
    setPermission(nextPermission);
    setStoredLocationPermission(nextPermission);
  }

  return (
    <div className="flex h-full w-full flex-col overflow-y-auto bg-[#faf9f7]">
      <div className="flex items-center px-6 pt-[calc(0.9rem+env(safe-area-inset-top))]">
        <PageBackButton ariaLabel="back-location-permission" onClick={handleBack} />
      </div>

      <section className="px-4 pb-8 pt-6">
        <SettingsGroup>
          <div className="border-b border-black/[0.04] px-5 py-4">
            <p className="text-sm font-medium text-[#809b9f]">允许读取位置信息</p>
          </div>

          <SettingsRow
            align="start"
            title="位置访问"
            titleClassName="text-[18px] font-medium tracking-[-0.02em] text-ink"
            description={locationEnabled ? "已允许应用尝试读取当前位置。" : "当前不会主动读取你的位置信息。"}
            descriptionClassName="text-muted-foreground"
            trailing={
              <Switch
                aria-label="toggle-location-permission"
                className="mt-0.5"
                checked={locationEnabled}
                onCheckedChange={handlePermissionChange}
              />
            }
          />
        </SettingsGroup>
      </section>
    </div>
  );
}
