import { User, Settings, Shield, Bell, ChevronRight } from "lucide-react";
import { Button } from "@/shared/ui";

export function ProfilePage() {
  return (
    <div className="flex h-full w-full flex-col bg-[#faf9f7] overflow-y-auto">
      {/* Header Profile Info */}
      <section className="px-6 pb-6 pt-12 flex flex-col items-center">
        <div className="relative mb-4 flex h-20 w-20 items-center justify-center rounded-full bg-[#f4ebd9] shadow-sm">
          <User className="h-10 w-10 text-[#d4704e]" />
        </div>
        <h2 className="text-xl font-bold text-ink">游客用户</h2>
        <p className="mt-1 text-sm text-[#809b9f]">探索未知的旅程</p>
      </section>

      {/* Action List */}
      <section className="px-4 pb-8 flex-1">
        <div className="rounded-2xl bg-white shadow-sm overflow-hidden">
          <div className="flex cursor-pointer items-center justify-between border-b px-4 py-4 hover:bg-black/5 transition-colors">
            <div className="flex items-center gap-3">
              <div className="rounded-full bg-blue-50 p-2 text-blue-500">
                <Bell className="h-4 w-4" />
              </div>
              <span className="text-sm font-medium text-ink">消息通知</span>
            </div>
            <ChevronRight className="h-4 w-4 text-[#809b9f]" />
          </div>

          <div className="flex cursor-pointer items-center justify-between border-b px-4 py-4 hover:bg-black/5 transition-colors">
            <div className="flex items-center gap-3">
              <div className="rounded-full bg-green-50 p-2 text-green-500">
                <Shield className="h-4 w-4" />
              </div>
              <span className="text-sm font-medium text-ink">隐私与安全</span>
            </div>
            <ChevronRight className="h-4 w-4 text-[#809b9f]" />
          </div>

          <div className="flex cursor-pointer items-center justify-between px-4 py-4 hover:bg-black/5 transition-colors">
            <div className="flex items-center gap-3">
              <div className="rounded-full bg-gray-100 p-2 text-gray-500">
                <Settings className="h-4 w-4" />
              </div>
              <span className="text-sm font-medium text-ink">通用设置</span>
            </div>
            <ChevronRight className="h-4 w-4 text-[#809b9f]" />
          </div>
        </div>

        <div className="mt-6 flex justify-center">
          <Button variant="outline" className="w-[80%] rounded-xl text-[#d4704e] border-[#d4704e]/30 hover:bg-[#d4704e]/10">
            退出登录
          </Button>
        </div>
      </section>
    </div>
  );
}
