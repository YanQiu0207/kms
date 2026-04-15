const dateFormatter = new Intl.DateTimeFormat("zh-CN", {
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
});

const integerFormatter = new Intl.NumberFormat("zh-CN");

export function formatDateTime(value: string | null | undefined): string {
  if (!value) {
    return "暂无时间";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return dateFormatter.format(parsed);
}

export function formatRelativeTime(value: string | null | undefined): string {
  if (!value) {
    return "未观测到事件";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  const diffMs = Date.now() - parsed.getTime();
  const diffSeconds = Math.round(diffMs / 1000);
  if (Math.abs(diffSeconds) < 60) {
    return `${diffSeconds} 秒前`;
  }
  const diffMinutes = Math.round(diffSeconds / 60);
  if (Math.abs(diffMinutes) < 60) {
    return `${diffMinutes} 分钟前`;
  }
  const diffHours = Math.round(diffMinutes / 60);
  if (Math.abs(diffHours) < 24) {
    return `${diffHours} 小时前`;
  }
  const diffDays = Math.round(diffHours / 24);
  return `${diffDays} 天前`;
}

export function formatLatency(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "--";
  }
  if (value >= 1000) {
    return `${(value / 1000).toFixed(2)} s`;
  }
  if (value >= 100) {
    return `${value.toFixed(0)} ms`;
  }
  return `${value.toFixed(1)} ms`;
}

export function formatCount(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "--";
  }
  return integerFormatter.format(value);
}

export function truncateText(value: string | null | undefined, limit = 60): string {
  if (!value) {
    return "暂无摘要";
  }
  if (value.length <= limit) {
    return value;
  }
  return `${value.slice(0, Math.max(0, limit - 1))}\u2026`;
}
