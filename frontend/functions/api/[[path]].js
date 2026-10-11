export async function onRequest(context) {
  const url = new URL(context.request.url);
  // 将 /api/* 透明转发到新的后端 API (api.aigoway.tech)
  const targetUrl = new URL(url.pathname + url.search, "https://api.aigoway.tech");

  // 构造代理请求并转发
  const newRequest = new Request(targetUrl.toString(), context.request);
  return fetch(newRequest);
}
