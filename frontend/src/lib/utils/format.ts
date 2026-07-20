// ============================================================================
// formatRelativeTime — 相对时间
// ============================================================================

const MINUTE_MS = 60 * 1000;
const HOUR_MS = 60 * MINUTE_MS;
const DAY_MS = 24 * HOUR_MS;

export function formatRelativeTime(date: string | Date): string {
  const target = typeof date === "string" ? new Date(date) : date;
  if (isNaN(target.getTime())) return "无效日期";

  const now = Date.now();
  const diffMs = now - target.getTime();
  const absDiffMs = Math.abs(diffMs);

  if (absDiffMs < MINUTE_MS) return "刚刚";

  const minutes = Math.floor(absDiffMs / MINUTE_MS);
  if (minutes < 60) {
    return diffMs > 0 ? `${minutes}分钟前` : `${minutes}分钟后`;
  }

  const hours = Math.floor(absDiffMs / HOUR_MS);
  if (hours < 24) {
    return diffMs > 0 ? `${hours}小时前` : `${hours}小时后`;
  }

  const days = Math.floor(absDiffMs / DAY_MS);
  if (days < 7) {
    return diffMs > 0 ? `${days}天前` : `${days}天后`;
  }

  // > 7 days: 显示绝对日期
  const y = target.getFullYear();
  const m = String(target.getMonth() + 1).padStart(2, "0");
  const d = String(target.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

// ============================================================================
// formatNumber — 数字格式化
// ============================================================================

const NUMBER_FORMATTER = new Intl.NumberFormat("zh-CN");

export function formatNumber(n: number): string {
  if (isNaN(n)) return "NaN";

  if (Math.abs(n) >= 1_000_000) {
    return (n / 1_000_000).toFixed(1).replace(/\.0$/, "") + "M";
  }
  if (Math.abs(n) >= 10_000) {
    return (n / 1_000).toFixed(1).replace(/\.0$/, "") + "k";
  }
  return NUMBER_FORMATTER.format(n);
}

// ============================================================================
// formatDuration — 毫秒转可读时长
// ============================================================================

export function formatDuration(ms: number): string {
  if (isNaN(ms) || ms < 0) return "0ms";

  if (ms < 1000) return `${ms}ms`;

  const totalSeconds = Math.floor(ms / 1000);
  if (totalSeconds < 60) return `${totalSeconds}s`;

  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);

  if (hours > 0 && minutes > 0) return `${hours}h ${minutes}m`;
  if (hours > 0) return `${hours}h`;
  return `${minutes}m`;
}

// ============================================================================
// truncate — 字符串截断
// ============================================================================

const ELLIPSIS = "...";

export function truncate(str: string, maxLength: number): string {
  if (maxLength <= ELLIPSIS.length) return str.slice(0, maxLength);
  if (str.length <= maxLength) return str;

  return str.slice(0, maxLength - ELLIPSIS.length) + ELLIPSIS;
}