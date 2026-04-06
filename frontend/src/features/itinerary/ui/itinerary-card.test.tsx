import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ItineraryCard } from "@/features/itinerary/ui/itinerary-card";

describe("ItineraryCard", () => {
  it("renders itinerary and followup blocks", () => {
    render(
      <ItineraryCard
        itinerary={[{ day: 1, city: "Hangzhou", activities: ["西湖骑行", "河坊街"] }]}
        followups={["你希望住在西湖还是钱江新城附近？"]}
      />, 
    );

    expect(screen.getByText("Day 1")).toBeInTheDocument();
    expect(screen.getByText("Hangzhou")).toBeInTheDocument();
    expect(screen.getByText("下一步建议")).toBeInTheDocument();
  });

  it("renders nothing when no data exists", () => {
    const { container } = render(<ItineraryCard itinerary={[]} followups={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
