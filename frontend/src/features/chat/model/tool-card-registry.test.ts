import { describe, it, expect } from "vitest";
import { resolveToolCard } from "@/features/chat/model/tool-card-registry";

describe("resolveToolCard", () => {
  it("returns null for non-hotel tool names", () => {
    expect(resolveToolCard("get_current_time", '{"time":"12:00"}')).toBeNull();
    expect(resolveToolCard("amap-mcp-server_searchPOI", '[]')).toBeNull();
  });

  it("returns null when output is not parseable JSON", () => {
    expect(resolveToolCard("rollinggo-hotel_searchHotels", "not json")).toBeNull();
    expect(resolveToolCard("rollinggo-hotel_searchHotels", null)).toBeNull();
    expect(resolveToolCard("rollinggo-hotel_searchHotels", undefined)).toBeNull();
  });

  it("parses hotel list from a direct array of hotel objects (string output)", () => {
    const output = JSON.stringify([
      { name: "如家酒店", price: 299, rating: 4.5, address: "北京朝阳区", star: 3 },
      { name: "汉庭酒店", price: 259, rating: 4.2, address: "北京海淀区", star: 3 },
    ]);
    const result = resolveToolCard("rollinggo-hotel_searchHotels", output);
    expect(result).not.toBeNull();
    expect(result!.type).toBe("hotel_list");
    expect(result!.items).toHaveLength(2);
    expect(result!.items[0].name).toBe("如家酒店");
    expect(result!.items[0].price).toBe(299);
    expect(result!.items[1].name).toBe("汉庭酒店");
  });

  it("parses hotel list from nested object with 'hotels' key", () => {
    const output = {
      hotels: [
        { name: "万豪酒店", pricePerNight: 899, score: 4.8, address: "上海浦东新区", starLevel: 5 },
      ],
      total: 1,
    };
    const result = resolveToolCard("rollinggo-hotel_searchHotels", output);
    expect(result).not.toBeNull();
    expect(result!.type).toBe("hotel_list");
    expect(result!.items).toHaveLength(1);
    expect(result!.items[0].name).toBe("万豪酒店");
    expect(result!.items[0].price).toBe(899);
    expect(result!.items[0].rating).toBe(4.8);
    expect(result!.items[0].star).toBe(5);
  });

  it("parses hotel list from nested object with 'data' key", () => {
    const output = JSON.stringify({
      data: [
        { name: "希尔顿", price: 1200, rating: 4.9, address: "深圳南山区", star: 5, tags: ["近地铁", "含早"] },
      ],
    });
    const result = resolveToolCard("rollinggo-hotel_searchHotels", output);
    expect(result).not.toBeNull();
    expect(result!.items[0].tags).toEqual(["近地铁", "含早"]);
  });

  it("parses a single hotel object", () => {
    const output = { name: "全季酒店", price: 350, address: "杭州西湖区" };
    const result = resolveToolCard("rollinggo-hotel_searchHotels", output);
    expect(result).not.toBeNull();
    expect(result!.type).toBe("hotel_list");
    expect(result!.items).toHaveLength(1);
    expect(result!.items[0].name).toBe("全季酒店");
  });

  it("returns null for hotel tool with non-hotel data", () => {
    const output = JSON.stringify({ message: "No hotels found", status: "empty" });
    expect(resolveToolCard("rollinggo-hotel_searchHotels", output)).toBeNull();
  });

  it("matches hotel tool names case-insensitively", () => {
    const output = JSON.stringify([{ name: "测试酒店", price: 100, address: "测试地址" }]);
    expect(resolveToolCard("some-HOTEL-tool", output)).not.toBeNull();
    expect(resolveToolCard("Hotel_Search", output)).not.toBeNull();
  });

  it("handles camelCase hotel fields (hotelName, lowestPrice)", () => {
    const output = JSON.stringify([
      { hotelName: "锦江之星", lowestPrice: 188, location: "广州天河", starLevel: 3 },
    ]);
    const result = resolveToolCard("hotel_search", output);
    expect(result).not.toBeNull();
    expect(result!.items[0].name).toBe("锦江之星");
    expect(result!.items[0].price).toBe(188);
    expect(result!.items[0].address).toBe("广州天河");
    expect(result!.items[0].star).toBe(3);
  });

  it("parses real rollinggo-hotel MCP response (structured_content.hotelInformationList)", () => {
    // 真实的 rollinggo-hotel MCP 工具返回结构
    const output = {
      structured_content: {
        message: "酒店搜索成功",
        hotelInformationList: [
          {
            hotelId: 99917,
            bookingUrl: "https://rollinggo.cn/pages/hotel/detail/index?id=99917",
            name: "成都富力丽思卡尔顿酒店(The Ritz-Carlton Chengdu)",
            brand: "万豪",
            address: "顺城大街269号",
            starRating: 5.0,
            price: { message: "实时价格", hasPrice: true, currency: "CNY", lowestPrice: 977.0 },
            imageUrl: "https://image-cdn.aigohotel.com/hotel/99917.jpg",
            hotelAmenities: ["免费WiFi", "停车场"],
            tags: ["单体酒店", "SPA服务", "免费WiFi"],
            description: "<p>酒店描述</p>",
            score: 4.8,
            latitude: 30.664021,
            longitude: 104.070074,
            distanceInMeters: 741,
            destinationId: "930",
            areaCode: "CN",
          },
          {
            hotelId: 88001,
            bookingUrl: "https://rollinggo.cn/pages/hotel/detail/index?id=88001",
            name: "成都香格里拉大酒店",
            brand: "香格里拉",
            address: "滨江东路9号",
            starRating: 5.0,
            price: { message: "实时价格", hasPrice: true, currency: "CNY", lowestPrice: 850.0 },
            imageUrl: "https://image-cdn.aigohotel.com/hotel/88001.jpg",
            hotelAmenities: ["游泳池", "健身房"],
            tags: ["河景房", "行政酒廊"],
            description: "<p>酒店描述</p>",
            score: 4.7,
            latitude: 30.645,
            longitude: 104.081,
            distanceInMeters: 1200,
            destinationId: "930",
            areaCode: "CN",
          },
        ],
      },
    };
    const result = resolveToolCard("rollinggo-hotel_searchHotels", output);
    expect(result).not.toBeNull();
    expect(result!.type).toBe("hotel_list");
    expect(result!.items).toHaveLength(2);

    const first = result!.items[0];
    expect(first.name).toBe("成都富力丽思卡尔顿酒店(The Ritz-Carlton Chengdu)");
    expect(first.id).toBe("99917");
    expect(first.brand).toBe("万豪");
    expect(first.address).toBe("顺城大街269号");
    expect(first.star).toBe(5);
    expect(first.price).toBe(977);
    expect(first.priceUnit).toBe("CNY");
    expect(first.rating).toBe(4.8);
    expect(first.imageUrl).toBe("https://image-cdn.aigohotel.com/hotel/99917.jpg");
    expect(first.bookingUrl).toBe("https://rollinggo.cn/pages/hotel/detail/index?id=99917");
    expect(first.tags).toEqual(["单体酒店", "SPA服务", "免费WiFi"]);

    const second = result!.items[1];
    expect(second.name).toBe("成都香格里拉大酒店");
    expect(second.price).toBe(850);
    expect(second.brand).toBe("香格里拉");
  });
});
