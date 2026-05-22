/**
 * Tool Card Registry
 *
 * 遵循主流 Agent 框架（ChatGPT / Gemini / Kimi / Doubao）的模式：
 * 通过 tool_name 识别工具类型，解析 output 并返回类型化的卡片数据。
 *
 * LangChain 对齐：
 * - tool output 来自 ToolMessage.artifact 或 ToolMessage.content
 * - 前端根据 tool_name + output schema 决定渲染方式
 * - 未识别的 output 回退为 JSON 展示（保持现有行为）
 */

// ──────────────────────────────────────────────
// Card data types (前端渲染所需的类型化数据)
// ──────────────────────────────────────────────

export interface HotelItem {
  id?: string;
  name: string;
  brand?: string;
  address?: string;
  price?: number;
  priceUnit?: string;
  /** 售罄等"无价但已知不可订"的提示信息（来自 RollingGo 的 price.message）。 */
  priceUnavailable?: string;
  rating?: number;
  star?: number;
  imageUrl?: string;
  bookingUrl?: string;
  tags?: string[];
  checkIn?: string;
  checkOut?: string;
  roomType?: string;
  breakfast?: string;
  /** 原始数据中的其他字段，保留供详情查看 */
  [key: string]: unknown;
}

export type ToolCardData =
  | { type: "hotel_list"; items: HotelItem[] }
  // 未来可扩展: | { type: "flight_list"; items: FlightItem[] }
  // 未来可扩展: | { type: "poi_list"; items: PoiItem[] }
  ;

// ──────────────────────────────────────────────
// Detection & parsing
// ──────────────────────────────────────────────

/**
 * 尝试将 tool output 解析为 JSON 对象/数组。
 * 支持 string (需 JSON.parse) 和已解析的对象。
 */
function tryParseOutput(output: unknown): unknown {
  if (output === null || output === undefined) return null;
  if (typeof output === "object") return output;
  if (typeof output === "string") {
    try {
      return JSON.parse(output);
    } catch {
      return null;
    }
  }
  return null;
}

/**
 * 检测对象是否具有酒店类似的字段结构。
 * 宽松匹配：只要有 name + (price 或 rating 或 address 或 star) 即判定为酒店。
 * 支持 rollinggo MCP 的真实数据格式：price 可能是 { lowestPrice, currency } 对象。
 */
function isHotelLike(obj: unknown): obj is Record<string, unknown> {
  if (typeof obj !== "object" || obj === null || Array.isArray(obj)) return false;
  const o = obj as Record<string, unknown>;
  // 必须有名称字段
  const hasName = typeof o.name === "string" || typeof o.hotelName === "string" || typeof o.hotel_name === "string";
  if (!hasName) return false;
  // 必须有至少一个酒店特征字段
  const hasPrice = typeof o.price === "number"
    || typeof o.pricePerNight === "number"
    || typeof o.price_per_night === "number"
    || typeof o.lowestPrice === "number"
    || typeof o.lowest_price === "number"
    // rollinggo 格式: price: { lowestPrice: number, currency: string }
    || (typeof o.price === "object" && o.price !== null && typeof (o.price as Record<string, unknown>).lowestPrice === "number");
  const hasRating = typeof o.rating === "number" || typeof o.score === "number";
  const hasAddress = typeof o.address === "string" || typeof o.location === "string";
  const hasStar = typeof o.star === "number"
    || typeof o.starLevel === "number"
    || typeof o.star_level === "number"
    || typeof o.starRating === "number";
  return hasPrice || hasRating || hasAddress || hasStar;
}

/**
 * 从 raw 对象中提取价格数值与"售罄"等无价提示。
 * 支持: 直接数字字段；rollinggo 格式 { lowestPrice: number, currency: string, hasPrice: boolean, message }
 */
function extractPrice(raw: Record<string, unknown>): { price?: number; unit?: string; unavailable?: string } {
  // 直接数字字段
  for (const key of ["price", "pricePerNight", "price_per_night", "lowestPrice", "lowest_price"]) {
    if (typeof raw[key] === "number" && raw[key] !== 0) return { price: raw[key] as number };
  }
  // 嵌套对象: price: { hasPrice, lowestPrice, currency, message }
  if (typeof raw.price === "object" && raw.price !== null) {
    const priceObj = raw.price as Record<string, unknown>;
    const val = Number(priceObj.lowestPrice ?? priceObj.lowest_price ?? 0);
    const unit = typeof priceObj.currency === "string" ? priceObj.currency : undefined;
    if (val > 0) return { price: val, unit };
    // hasPrice === false：保留售罄等提示，便于卡片继续展示状态与 bookingUrl
    if (priceObj.hasPrice === false) {
      const unavailable = typeof priceObj.message === "string" && priceObj.message.trim()
        ? (priceObj.message as string).trim()
        : "暂未开放";
      return { unavailable };
    }
  }
  return {};
}

/**
 * 将原始对象规范化为 HotelItem。
 * 支持 rollinggo MCP 真实格式 + 多种通用字段名。
 */
function normalizeHotelItem(raw: Record<string, unknown>): HotelItem {
  const { price, unit, unavailable } = extractPrice(raw);
  return {
    id: String(raw.id ?? raw.hotelId ?? raw.hotel_id ?? ""),
    name: String(raw.name ?? raw.hotelName ?? raw.hotel_name ?? ""),
    brand: raw.brand ? String(raw.brand) : undefined,
    address: String(raw.address ?? raw.location ?? ""),
    price,
    priceUnit: unit ?? (typeof raw.priceUnit === "string" ? raw.priceUnit : typeof raw.price_unit === "string" ? raw.price_unit : typeof raw.currency === "string" ? raw.currency : "CNY"),
    priceUnavailable: unavailable,
    rating: Number(raw.rating ?? raw.score ?? 0) || undefined,
    star: Number(raw.star ?? raw.starLevel ?? raw.star_level ?? raw.starRating ?? raw.star_rating ?? 0) || undefined,
    imageUrl: String(raw.imageUrl ?? raw.image_url ?? raw.image ?? raw.coverImage ?? raw.cover_image ?? raw.img ?? ""),
    bookingUrl: raw.bookingUrl ? String(raw.bookingUrl) : raw.booking_url ? String(raw.booking_url) : undefined,
    tags: Array.isArray(raw.tags) ? raw.tags.map(String) : undefined,
    checkIn: raw.checkIn ? String(raw.checkIn) : raw.check_in ? String(raw.check_in) : undefined,
    checkOut: raw.checkOut ? String(raw.checkOut) : raw.check_out ? String(raw.check_out) : undefined,
    roomType: raw.roomType ? String(raw.roomType) : raw.room_type ? String(raw.room_type) : undefined,
    breakfast: raw.breakfast ? String(raw.breakfast) : undefined,
  };
}

/**
 * 从数组中提取酒店列表。
 * 要求至少有 1 个元素且第一个元素符合酒店 schema。
 */
function extractHotelList(arr: unknown[]): HotelItem[] | null {
  if (arr.length === 0) return null;
  // 检查前几个元素是否为酒店结构
  const sample = arr.slice(0, 3);
  if (!sample.every(isHotelLike)) return null;
  return arr.filter(isHotelLike).map(normalizeHotelItem);
}

// ──────────────────────────────────────────────
// Main API
// ──────────────────────────────────────────────

/**
 * 在对象的值中查找酒店数组。
 * 遍历所有值，找到第一个可被解析为酒店列表的数组。
 */
function findHotelArray(obj: Record<string, unknown>): HotelItem[] | null {
  for (const val of Object.values(obj)) {
    if (Array.isArray(val)) {
      const items = extractHotelList(val);
      if (items && items.length > 0) return items;
    }
  }
  return null;
}

/**
 * 根据 tool_name 和 output 尝试解析卡片数据。
 * 返回 null 表示不适合卡片展示（回退为默认行为）。
 *
 * 遵循主流 Agent 模式：tool_name → 类型路由 → schema 验证 → 结构化数据
 */
export function resolveToolCard(toolName: string, output: unknown): ToolCardData | null {
  // Step 1: tool_name 路由（主流 Agent 均通过工具名判断渲染类型）
  const isHotelTool = /hotel/i.test(toolName);
  if (!isHotelTool) return null;

  // Step 2: 解析 output
  const parsed = tryParseOutput(output);
  if (parsed === null) return null;

  // Step 3: 检测数据结构
  // 情况 A: 直接是数组
  if (Array.isArray(parsed)) {
    const items = extractHotelList(parsed);
    if (items && items.length > 0) return { type: "hotel_list", items };
    return null;
  }

  // 情况 B: 嵌套在对象中
  if (typeof parsed === "object" && parsed !== null) {
    const obj = parsed as Record<string, unknown>;
    // 尝试直接在顶层找数组字段
    const found = findHotelArray(obj);
    if (found) return { type: "hotel_list", items: found };

    // 尝试一层嵌套（rollinggo 格式: { structured_content: { hotelInformationList: [...] } }）
    for (const val of Object.values(obj)) {
      if (typeof val === "object" && val !== null && !Array.isArray(val)) {
        const nested = findHotelArray(val as Record<string, unknown>);
        if (nested) return { type: "hotel_list", items: nested };
      }
    }

    // 情况 C: 单个酒店对象
    if (isHotelLike(obj)) {
      return { type: "hotel_list", items: [normalizeHotelItem(obj)] };
    }
  }

  return null;
}
