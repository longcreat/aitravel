import { describe, it, expect } from "vitest";

import {
  getCardListRenderer,
  groupCardsByType,
} from "@/features/chat/model/tool-card-registry";
import type { StructuredCard } from "@/features/chat/model/chat.types";

function makeCard(overrides: Partial<StructuredCard> = {}): StructuredCard {
  return {
    type: "card",
    id: "card-1",
    card_type: "hotel",
    data: { name: "桔子酒店", price: 277 },
    ...overrides,
  };
}

describe("groupCardsByType", () => {
  it("returns empty array for empty input", () => {
    expect(groupCardsByType([])).toEqual([]);
  });

  it("groups consecutive cards of the same type", () => {
    const groups = groupCardsByType([
      makeCard({ id: "card-1", card_type: "hotel" }),
      makeCard({ id: "card-2", card_type: "hotel" }),
    ]);

    expect(groups).toHaveLength(1);
    expect(groups[0].cardType).toBe("hotel");
    expect(groups[0].cards.map((c) => c.id)).toEqual(["card-1", "card-2"]);
  });

  it("starts a new group when the type changes", () => {
    const groups = groupCardsByType([
      makeCard({ id: "card-1", card_type: "hotel" }),
      makeCard({ id: "card-2", card_type: "flight" }),
      makeCard({ id: "card-3", card_type: "flight" }),
      makeCard({ id: "card-4", card_type: "hotel" }),
    ]);

    expect(groups.map((g) => g.cardType)).toEqual(["hotel", "flight", "hotel"]);
    expect(groups[0].cards).toHaveLength(1);
    expect(groups[1].cards).toHaveLength(2);
    expect(groups[2].cards).toHaveLength(1);
  });
});

describe("getCardListRenderer", () => {
  it("returns the hotel renderer for card_type='hotel'", () => {
    expect(getCardListRenderer("hotel")).not.toBeNull();
  });

  it("returns null for unknown card types (caller falls back to default rendering)", () => {
    expect(getCardListRenderer("flight")).toBeNull();
    expect(getCardListRenderer("itinerary")).toBeNull();
    expect(getCardListRenderer("unknown-domain")).toBeNull();
  });
});
