const exactToolDisplayNameMap: Record<string, string> = {
  amap_mcp_server_maps_text_search: "高德地图 · 文本搜索",
  amap_mcp_server_maps_weather: "高德地图 · 天气查询",
  amap_mcp_server_maps_reverse_geocode: "高德地图 · 逆地理编码",
  amap_mcp_server_maps_around_search: "高德地图 · 周边搜索",
  amap_mcp_server_maps_geo: "高德地图 · 地理编码",
};

const suffixToolDisplayNameMap: Record<string, string> = {
  maps_text_search: "文本搜索",
  maps_weather: "天气查询",
  maps_reverse_geocode: "逆地理编码",
  maps_around_search: "周边搜索",
  maps_geo: "地理编码",
};

function normalizeToolNameForLookup(toolName: string): string {
  return toolName.trim().replace(/[\s-]+/g, "_");
}

function fallbackFormatToolName(toolName: string): string {
  return toolName.replace(/[_-]+/g, " ").trim();
}

export function getToolDisplayName(toolName: string): string {
  const normalizedToolName = toolName.trim();
  if (!normalizedToolName) {
    return "unknown";
  }

  const normalizedLookupName = normalizeToolNameForLookup(normalizedToolName);

  const exactMatch = exactToolDisplayNameMap[normalizedLookupName] ?? exactToolDisplayNameMap[normalizedToolName];
  if (exactMatch) {
    return exactMatch;
  }

  const matchingSuffix = Object.keys(suffixToolDisplayNameMap).find((suffix) =>
    normalizedLookupName === suffix ||
    normalizedLookupName.endsWith(`_${suffix}`) ||
    normalizedLookupName.endsWith(`-${suffix}`),
  );

  if (matchingSuffix) {
    return suffixToolDisplayNameMap[matchingSuffix];
  }

  return fallbackFormatToolName(normalizedToolName);
}

export const toolDisplayNameMap = {
  exact: exactToolDisplayNameMap,
  suffix: suffixToolDisplayNameMap,
};
