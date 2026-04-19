import { useState } from "react";
import { createPortal } from "react-dom";
import { ArrowLeft, ExternalLink, RefreshCw } from "lucide-react";

import { useAppSurfaceOverlayRoot } from "@/shared/layouts/app-surface-overlay";

interface InAppBrowserSheetProps {
  url: string | null;
  onClose: () => void;
}

function extractDomain(url: string): string {
  try {
    return new URL(url).hostname;
  } catch {
    return url;
  }
}

export function InAppBrowserSheet({ url, onClose }: InAppBrowserSheetProps) {
  const overlayRoot = useAppSurfaceOverlayRoot();
  const [refreshKey, setRefreshKey] = useState(0);

  if (!url || !overlayRoot) {
    return null;
  }

  const domain = extractDomain(url);

  function handleRefresh() {
    setRefreshKey((k) => k + 1);
  }

  function handleOpenExternal() {
    window.open(url!, "_blank", "noopener,noreferrer");
  }

  return createPortal(
    <div className="absolute inset-0 z-50 flex flex-col bg-white pointer-events-auto overflow-hidden">
      {/* Toolbar */}
      <div className="shrink-0 border-b border-[#e8e3da] bg-[#f8f4ee] px-3 pb-2 pt-[calc(0.75rem+env(safe-area-inset-top))]">
        <div className="flex h-10 items-center gap-2">
          <button
            type="button"
            aria-label="关闭内嵌浏览器"
            className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-full text-[#5f5a52] transition-colors hover:bg-[#ede8df]"
            onClick={onClose}
          >
            <ArrowLeft className="h-5 w-5" />
          </button>

          <div className="min-w-0 flex-1 truncate rounded-[8px] bg-[#ede8df] px-3 py-1.5 text-center text-[14px] font-medium text-[#5f5a52]">
            {domain}
          </div>

          <button
            type="button"
            aria-label="刷新页面"
            className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-full text-[#5f5a52] transition-colors hover:bg-[#ede8df]"
            onClick={handleRefresh}
          >
            <RefreshCw className="h-5 w-5" />
          </button>

          <button
            type="button"
            aria-label="在浏览器中打开"
            className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-full text-[#5f5a52] transition-colors hover:bg-[#ede8df]"
            onClick={handleOpenExternal}
          >
            <ExternalLink className="h-5 w-5" />
          </button>
        </div>
      </div>

      {/* iframe 容器：wrapper 占据 flex 剩余空间，iframe 用 absolute 填满，避免 iframe 元素自身产生 scroll viewport */}
      <div className="relative min-h-0 flex-1 overflow-hidden">
        <iframe
          key={refreshKey}
          src={url}
          className="absolute left-0 top-0 bottom-0 h-full w-full border-0"
          scrolling="no"
          sandbox="allow-scripts allow-forms allow-same-origin allow-popups"
          title={domain}
        />
      </div>
    </div>,
    overlayRoot,
  );
}
