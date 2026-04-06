import { MapPin, Sparkles } from "lucide-react";

import type { ItineraryItem } from "@/features/chat/model/chat.types";
import { Badge } from "@/shared/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/shared/ui/card";

interface ItineraryCardProps {
  itinerary: ItineraryItem[];
  followups?: string[];
}

export function ItineraryCard({ itinerary, followups = [] }: ItineraryCardProps) {
  if (!itinerary.length && !followups.length) {
    return null;
  }

  return (
    <Card className="mt-3 bg-white/90">
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle className="text-ink">结构化行程</CardTitle>
        <Badge className="gap-1">
          <Sparkles className="h-3 w-3" />
          AI Plan
        </Badge>
      </CardHeader>
      <CardContent className="space-y-3">
        {itinerary.map((item) => (
          <div key={`${item.day}-${item.city}`} className="rounded-2xl bg-[#fff8ef] p-3 shadow-sm">
            <div className="mb-2 flex items-center justify-between">
              <span className="font-display text-sm font-bold text-ink">Day {item.day}</span>
              <span className="inline-flex items-center gap-1 text-xs text-[#35565a]">
                <MapPin className="h-3.5 w-3.5" />
                {item.city}
              </span>
            </div>
            <ul className="m-0 list-disc space-y-1 pl-4 text-sm text-[#223f43]">
              {item.activities.map((activity, index) => (
                <li key={`${item.day}-${index}`}>{activity}</li>
              ))}
            </ul>
            {item.notes ? <p className="mt-2 text-xs text-[#4f696d]">备注：{item.notes}</p> : null}
          </div>
        ))}

        {followups.length ? (
          <div className="rounded-2xl bg-[#fff4f1] p-3 shadow-sm">
            <p className="mb-1 text-xs font-semibold text-[#8d3b2f]">下一步建议</p>
            <ul className="m-0 list-disc space-y-1 pl-4 text-sm text-[#8d3b2f]">
              {followups.map((item, index) => (
                <li key={index}>{item}</li>
              ))}
            </ul>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
