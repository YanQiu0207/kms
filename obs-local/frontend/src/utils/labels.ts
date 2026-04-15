import type { UiLocaleMode } from "@/types/observability";
import { renderLocale } from "@/utils/i18n";

function cleanSegment(value: string | null | undefined): string {
  return (value ?? "").trim().toLowerCase();
}

export function requestTypeLabel(value: string | null | undefined, mode: UiLocaleMode): string {
  const normalized = cleanSegment(value);
  if (normalized === "ask") {
    return renderLocale(mode, "问答", "Ask");
  }
  if (normalized === "search") {
    return renderLocale(mode, "检索", "Search");
  }
  if (normalized === "stats") {
    return renderLocale(mode, "统计", "Stats");
  }
  if (normalized === "verify") {
    return renderLocale(mode, "校验", "Verify");
  }
  if (normalized === "health") {
    return renderLocale(mode, "健康检查", "Health");
  }
  if (normalized === "index") {
    return renderLocale(mode, "索引", "Index");
  }
  return renderLocale(mode, "请求", "Request");
}

export function routeLabel(path: string | null | undefined, requestType: string | null | undefined, mode: UiLocaleMode): string {
  const normalizedPath = cleanSegment(path);
  if (normalizedPath.endsWith("/ask")) {
    return renderLocale(mode, "问答接口", "Ask Endpoint");
  }
  if (normalizedPath.endsWith("/search")) {
    return renderLocale(mode, "检索接口", "Search Endpoint");
  }
  if (normalizedPath.endsWith("/stats")) {
    return renderLocale(mode, "统计接口", "Stats Endpoint");
  }
  if (normalizedPath.endsWith("/verify")) {
    return renderLocale(mode, "校验接口", "Verify Endpoint");
  }
  if (normalizedPath.endsWith("/health")) {
    return renderLocale(mode, "健康接口", "Health Endpoint");
  }
  return renderLocale(mode, `${requestTypeLabel(requestType, "zh")}接口`, `${requestTypeLabel(requestType, "en")} Endpoint`);
}

export function stageLabel(stage: string | null | undefined, mode: UiLocaleMode): string {
  const normalized = cleanSegment(stage);
  if (normalized.startsWith("http.")) {
    return renderLocale(mode, "HTTP 请求", "HTTP Request");
  }
  if (normalized.startsWith("api.")) {
    return renderLocale(mode, "接口处理", "API Handling");
  }
  if (normalized.startsWith("query.")) {
    return renderLocale(mode, "查询流程", "Query Flow");
  }
  if (normalized.startsWith("retrieval.")) {
    return renderLocale(mode, "召回阶段", "Retrieval Stage");
  }
  if (normalized.startsWith("reranker.")) {
    return renderLocale(mode, "重排阶段", "Rerank Stage");
  }
  if (normalized.startsWith("embedding.")) {
    return renderLocale(mode, "向量编码", "Embedding");
  }
  if (normalized.startsWith("semantic.")) {
    return renderLocale(mode, "语义检索", "Semantic Retrieval");
  }
  if (normalized.startsWith("registry.")) {
    return renderLocale(mode, "注册表处理", "Registry Work");
  }
  return renderLocale(mode, "技术阶段", "Technical Stage");
}

export function eventLabel(
  event: string | null | undefined,
  fallback: string | null | undefined,
  mode: UiLocaleMode,
): string {
  const normalized = cleanSegment(event);
  if (normalized.startsWith("http.request")) {
    return renderLocale(mode, "HTTP 请求事件", "HTTP Request Event");
  }
  if (normalized.startsWith("api.ask")) {
    return renderLocale(mode, "问答接口事件", "Ask API Event");
  }
  if (normalized.startsWith("api.search")) {
    return renderLocale(mode, "检索接口事件", "Search API Event");
  }
  if (normalized.startsWith("query.ask")) {
    return renderLocale(mode, "问答流程事件", "Ask Flow Event");
  }
  if (normalized.startsWith("query.search")) {
    return renderLocale(mode, "检索流程事件", "Search Flow Event");
  }
  if (normalized.startsWith("reranker.")) {
    return renderLocale(mode, "重排事件", "Rerank Event");
  }
  if (normalized.startsWith("embedding.")) {
    return renderLocale(mode, "向量编码事件", "Embedding Event");
  }
  if (normalized.startsWith("semantic.")) {
    return renderLocale(mode, "语义检索事件", "Semantic Retrieval Event");
  }
  if (fallback) {
    return fallback;
  }
  return renderLocale(mode, "技术事件", "Technical Event");
}
