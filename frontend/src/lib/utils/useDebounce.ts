"use client";

import { useState, useEffect, useRef, useCallback } from "react";

// ============================================================================
// useDebounce — debounce a value
// ============================================================================

/**
 * 对传入的 value 做防抖处理, delay ms 内无变化时返回最新值
 */
export function useDebounce<T>(value: T, delay: number): T {
  const [debouncedValue, setDebouncedValue] = useState(value);

  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedValue(value);
    }, delay);

    return () => {
      clearTimeout(timer);
    };
  }, [value, delay]);

  return debouncedValue;
}

// ============================================================================
// useDebouncedCallback — debounce a callback
// ============================================================================

/**
 * 对回调函数做防抖处理, 连续调用时仅最后一次在 delay ms 后执行
 * 返回的 callback 引用稳定(identity stable), 不会随 fn/delay 变化而重建
 */
export function useDebouncedCallback<T extends (...args: never[]) => unknown>(
  fn: T,
  delay: number
): T {
  const fnRef = useRef(fn);
  const delayRef = useRef(delay);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // 保持 ref 始终指向最新的 fn 和 delay
  fnRef.current = fn;
  delayRef.current = delay;

  // 组件卸载时清理 timer
  useEffect(() => {
    return () => {
      if (timerRef.current !== null) {
        clearTimeout(timerRef.current);
      }
    };
  }, []);

  const debouncedFn = useCallback((...args: Parameters<T>) => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
    }
    timerRef.current = setTimeout(() => {
      fnRef.current(...args);
    }, delayRef.current);
  }, []) as T;

  return debouncedFn;
}