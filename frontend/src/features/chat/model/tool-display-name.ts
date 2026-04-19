/**
 * 本地工具展示名称表。
 * key 是后端 local_tools.py 中 @tool 装饰器注册的函数名。
 */
const localToolRegistry: Record<string, string> = {
  get_current_time: "获取当前时间",
  request_user_clarification: "补充信息",
};

/**
 * MCP 工具展示名称注册表。
 *
 * 以 MCP 服务器为维度组织：每个 key 是后端 mcp.servers.json 中的服务器名称
 * 经 langchain-mcp-adapters 规范化后的前缀（连字符转下划线、统一小写）。
 * tools 中的 key 是去掉服务器前缀后的原始工具名。
 *
 * 展示格式："{serverLabel} · {toolLabel}"，若工具未注册则退回格式化原始名称。
 */
const serverRegistry: Record<string, { label: string; tools: Record<string, string> }> = {
  "amap-mcp-server": {
    label: "高德地图",
    tools: {
      maps_text_search: "文本搜索",
      maps_weather: "天气查询",
      maps_reverse_geocode: "逆地理编码",
      maps_around_search: "周边搜索",
      maps_geo: "地理编码",
    },
  },
  "rollinggo-hotel": {
    label: "RollingGo",
    tools: {
      getHotelSearchTags: "搜索标签",
      searchHotels: "搜索酒店",
      getHotelDetail: "酒店详情",
    },
  },
  "exa": {
    label: "Exa",
    tools: {
      web_search_exa: "网络搜索",
      web_search_advanced_exa: "高级网络搜索",
      web_fetch_exa: "网络内容获取"
    },
  },
};

function fallbackFormatToolName(toolName: string): string {
  return toolName.replace(/[_-]+/g, " ").trim();
}

export function getToolDisplayName(toolName: string): string {
  const name = toolName.trim();
  if (!name) return "unknown";

  // 优先匹配本地工具（无前缀，精确匹配）
  if (localToolRegistry[name]) return localToolRegistry[name];

  // 按服务器前缀匹配 MCP 工具
  for (const [prefix, { label, tools }] of Object.entries(serverRegistry)) {
    if (name === prefix || name.startsWith(`${prefix}_`)) {
      const toolKey = name === prefix ? "" : name.slice(prefix.length + 1);
      const toolLabel = tools[toolKey];
      if (toolLabel) return `${label} · ${toolLabel}`;
      if (toolKey) return `${label} · ${fallbackFormatToolName(toolKey)}`;
    }
  }

  return fallbackFormatToolName(name);
}

export const toolDisplayNameMap = { local: localToolRegistry, servers: serverRegistry };
