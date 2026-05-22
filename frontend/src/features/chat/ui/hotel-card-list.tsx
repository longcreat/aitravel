/**
 * HotelCardList — 酒店搜索结果卡片列表
 *
 * 设计对标 Doubao(豆包) / Kimi / ChatGPT 的工具结果卡片：
 * - 横向可滚动的卡片列表（移动端友好）
 * - 每张卡片展示关键信息：名称、评分、星级、价格、标签
 * - 紧凑布局，不占过多垂直空间
 */

import { MapPin, Star } from "lucide-react";
import type { HotelItem } from "@/features/chat/model/tool-card-registry";
import { useBrowser } from "@/shared/lib/browser";

interface HotelCardListProps {
  items: HotelItem[];
}

const CURRENCY_SYMBOLS: Record<string, string> = {
  CNY: "¥",
  USD: "$",
  EUR: "€",
  GBP: "£",
  JPY: "¥",
  KRW: "₩",
  HKD: "HK$",
  TWD: "NT$",
  THB: "฿",
  SGD: "S$",
};

function formatPrice(price: number, unit?: string): string {
  const symbol = CURRENCY_SYMBOLS[(unit || "CNY").toUpperCase()] ?? `${unit} `;
  return `${symbol}${price}`;
}

function StarRating({ star }: { star: number }) {
  return (
    <span className="inline-flex items-center gap-0.5 text-[#e6a23c]">
      {Array.from({ length: Math.min(star, 5) }, (_, i) => (
        <Star key={i} className="h-3 w-3 fill-current" />
      ))}
    </span>
  );
}

function HotelCard({ hotel, onOpenUrl }: { hotel: HotelItem; onOpenUrl: (url: string) => void }) {
  const displayName = hotel.name || "未知酒店";
  const hasImage = hotel.imageUrl && hotel.imageUrl !== "undefined" && hotel.imageUrl !== "";

  return (
    <div className="flex min-w-[180px] max-w-[200px] shrink-0 flex-col overflow-hidden rounded-xl border border-[#e8e4dc] bg-white shadow-sm transition-shadow hover:shadow-md">
      {/* 图片区域 */}
      {hasImage ? (
        <div className="h-[100px] w-full overflow-hidden bg-[#f5f0ea]">
          <img
            src={hotel.imageUrl}
            alt={displayName}
            className="h-full w-full object-cover"
            loading="lazy"
            referrerPolicy="no-referrer"
            crossOrigin="anonymous"
            onError={(e) => {
              const img = e.target as HTMLImageElement;
              // 第一次失败尝试去掉 crossOrigin 重试
              if (img.crossOrigin) {
                img.crossOrigin = null;
                img.src = hotel.imageUrl!;
              } else {
                img.style.display = "none";
              }
            }}
          />
        </div>
      ) : (
        <div className="flex h-[60px] w-full items-center justify-center bg-gradient-to-br from-[#f5f0ea] to-[#ebe5db]">
          <MapPin className="h-5 w-5 text-[#c4b9a8]" />
        </div>
      )}

      {/* 内容区域 */}
      <div className="flex flex-1 flex-col gap-1 px-2.5 py-2">
        {/* 名称 + 星级 */}
        <div className="flex items-start justify-between gap-1">
          <h4 className="line-clamp-2 text-[13px] font-semibold leading-tight text-[#2c2b28]">
            {displayName}
          </h4>
          {hotel.star ? <StarRating star={hotel.star} /> : null}
        </div>

        {/* 品牌 */}
        {hotel.brand ? (
          <span className="text-[11px] text-[#a09a8f]">{hotel.brand}</span>
        ) : null}

        {/* 地址 */}
        {hotel.address ? (
          <p className="line-clamp-1 text-[12px] text-[#8a857b]">
            <MapPin className="mr-0.5 inline h-3 w-3" />
            {hotel.address}
          </p>
        ) : null}

        {/* 标签 */}
        <div className="flex flex-wrap items-center gap-1.5">
          {hotel.tags?.slice(0, 3).map((tag) => (
            <span
              key={tag}
              className="rounded-md bg-[#f0f7f4] px-1.5 py-0.5 text-[11px] text-[#6d8a6f]"
            >
              {tag}
            </span>
          ))}
        </div>

        {/* 房型 + 早餐 */}
        {(hotel.roomType || hotel.breakfast) ? (
          <p className="text-[12px] text-[#8a857b]">
            {hotel.roomType ? <span>{hotel.roomType}</span> : null}
            {hotel.roomType && hotel.breakfast ? <span className="mx-1">·</span> : null}
            {hotel.breakfast ? <span>{hotel.breakfast}</span> : null}
          </p>
        ) : null}

        {/* 价格 + 预订链接：即使售罄/无价，只要有 bookingUrl 仍提供入口 */}
        {(hotel.price || hotel.priceUnavailable || hotel.bookingUrl) ? (
          <div className="mt-auto flex items-end justify-between gap-2 pt-1">
            <div className="min-w-0">
              {hotel.price ? (
                <>
                  <span className="text-[16px] font-bold text-[#e85d3a]">{formatPrice(hotel.price, hotel.priceUnit)}</span>
                  <span className="ml-0.5 text-[11px] text-[#8a857b]">/晚起</span>
                </>
              ) : hotel.priceUnavailable ? (
                <span className="text-[12px] text-[#a09a8f]">{hotel.priceUnavailable}</span>
              ) : null}
            </div>
            {hotel.bookingUrl ? (
              <button
                type="button"
                onClick={() => onOpenUrl(hotel.bookingUrl!)}
                className="shrink-0 rounded-md bg-[#e85d3a] px-2 py-0.5 text-[11px] text-white hover:bg-[#d04e2e]"
              >
                {hotel.price ? "预订" : "查看"}
              </button>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}

export function HotelCardList({ items }: HotelCardListProps) {
  const { openUrl } = useBrowser();

  if (items.length === 0) return null;

  return (
    <div className="my-2 -mx-1">
      <div className="flex gap-2.5 overflow-x-auto px-1 pb-2 [&::-webkit-scrollbar]:hidden [-ms-overflow-style:none] [scrollbar-width:none]">
        {items.map((hotel, idx) => (
          <HotelCard key={hotel.id || `hotel-${idx}`} hotel={hotel} onOpenUrl={openUrl} />
        ))}
      </div>
      <p className="mt-1 text-[11px] text-[#b0ab9f]">
        共 {items.length} 家酒店
      </p>
    </div>
  );
}
