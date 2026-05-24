/**
 * 卡片渲染器注册表
 *
 * 后端在工具调用返回时已经把原始 payload 解析成类型化的 `StructuredCard`
 * （见 `backend/app/agent/cards.py`）。前端拿到的 `tool.cards` 数组里每条都
 * 自带 `card_type`，本模块只做一件事：把 `card_type` 映射到具体的渲染器。
 *
 * 新增一种卡片（机票 / 行程 / POI ...）只需要：
 *
 *   1. 后端实现一个 `CardExtractor`，注册到 `CARD_EXTRACTORS`。
 *   2. 前端在 `cardListRenderers` 注册一个组件，处理 `data` 字典。
 *
 * 不需要修改 `chat-message.tsx` / `streaming.py` / 类型系统。
 *
 * 设计决定（2026-05-24）：与 ChatGPT / Doubao / Kimi 一致，**卡片只在工具
 * chip 下方以列表形式展示**，不做"图文交错"。LLM 自由文本与卡片渲染完全
 * 解耦，避免了从 LLM 自然语言里反向解析结构带来的所有不稳定问题（参见
 * 同期被废弃的 `card_anchors` 方案）。
 */

import type { ComponentType } from "react";

import type { StructuredCard } from "@/features/chat/model/chat.types";
import { HotelCardList, type HotelItem } from "@/features/chat/ui/hotel-card-list";

// ──────────────────────────────────────────────
// Registry contract
// ──────────────────────────────────────────────

/**
 * 列表型卡片渲染器：一组同类型卡片渲染成一段 UI（典型如酒店列表横滑、机票
 * 列表竖排）。组件自行决定空数组的处理（绝大多数应当返回 `null`）。
 */
export interface CardListRendererProps<TData = Record<string, unknown>> {
  cards: ReadonlyArray<StructuredCard & { data: TData }>;
}

export type CardListRenderer<TData = Record<string, unknown>> = ComponentType<
  CardListRendererProps<TData>
>;

// ──────────────────────────────────────────────
// Adapter: HotelCardList
// ──────────────────────────────────────────────

/**
 * 把后端 `StructuredCard.data`（已经是 `HotelItem` 形状的小驼峰对象）
 * 适配成 `HotelCardList` 的 `items` 入参。
 */
function HotelCardListAdapter({ cards }: CardListRendererProps<HotelItem>) {
  if (cards.length === 0) return null;
  const items = cards.map((card) => card.data);
  return <HotelCardList items={items} />;
}

// ──────────────────────────────────────────────
// Registry
// ──────────────────────────────────────────────

const cardListRenderers: Record<string, CardListRenderer<any>> = {
  hotel: HotelCardListAdapter,
  // 新增卡片类型在此追加：
  //   flight: FlightCardListAdapter,
  //   itinerary: ItineraryCardListAdapter,
  //   poi: PoiCardListAdapter,
};

// ──────────────────────────────────────────────
// Public API
// ──────────────────────────────────────────────

/**
 * 取出某 `card_type` 对应的列表渲染器；未注册时返回 `null`，调用方按未识别处理。
 */
export function getCardListRenderer(cardType: string): CardListRenderer | null {
  return cardListRenderers[cardType] ?? null;
}

/**
 * 把一组 `StructuredCard` 按 `card_type` 分组，保持原数组顺序：每段内同类型连续
 * 出现的卡片会被合到一组。便于 chat-message 直接调用 `getCardListRenderer`
 * 一次渲染一组同类卡片。
 */
export function groupCardsByType(
  cards: ReadonlyArray<StructuredCard>,
): Array<{ cardType: string; cards: StructuredCard[] }> {
  if (cards.length === 0) return [];
  const groups: Array<{ cardType: string; cards: StructuredCard[] }> = [];
  for (const card of cards) {
    const last = groups[groups.length - 1];
    if (last && last.cardType === card.card_type) {
      last.cards.push(card);
    } else {
      groups.push({ cardType: card.card_type, cards: [card] });
    }
  }
  return groups;
}
