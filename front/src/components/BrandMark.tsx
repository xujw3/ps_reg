import { useId } from "react";
import { cn } from "@/lib/utils";

/**
 * ProxyScrape Register 品牌图标：深紫蓝渐变方块 + 六节点代理网络 +
 * 青色雷达扫描弧。代理池（节点互联）与监控（扫描）双重意象。
 */
export function BrandMark({ className = "h-9 w-9" }: { className?: string }) {
  const uid = useId().replace(/[^a-zA-Z0-9_-]/g, "");
  const bgId = `ps-bg-${uid}`;
  const coreId = `ps-core-${uid}`;
  const glowId = `ps-glow-${uid}`;
  return (
    <span className={cn("inline-flex shrink-0 items-center justify-center", className)}>
      <svg viewBox="0 0 64 64" className="h-full w-full" aria-hidden="true" focusable="false">
        <defs>
          <linearGradient id={bgId} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#141d3a" />
            <stop offset="1" stopColor="#2e1065" />
          </linearGradient>
          <linearGradient id={coreId} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#a78bfa" />
            <stop offset="0.6" stopColor="#7c3aed" />
            <stop offset="1" stopColor="#22d3ee" />
          </linearGradient>
          <radialGradient id={glowId} cx="0.5" cy="0.5" r="0.5">
            <stop offset="0" stopColor="#22d3ee" stopOpacity="0.5" />
            <stop offset="1" stopColor="#22d3ee" stopOpacity="0" />
          </radialGradient>
        </defs>

        {/* 背景 */}
        <rect width="64" height="64" rx="15" fill={`url(#${bgId})`} />

        {/* 顶部高光 */}
        <path
          d="M8 14.5A6.5 6.5 0 0 1 14.5 8h35A6.5 6.5 0 0 1 56 14.5V20H8v-5.5z"
          fill="#ffffff"
          opacity="0.07"
        />

        {/* 中心光晕 */}
        <circle cx="32" cy="30" r="16" fill={`url(#${glowId})`} />

        {/* 网络连线 */}
        <g stroke="#8b5cf6" strokeWidth="2" strokeLinecap="round" opacity="0.65">
          <path d="M32 30 L17 20" />
          <path d="M32 30 L47 20" />
          <path d="M32 30 L52 35" />
          <path d="M32 30 L47 48" />
          <path d="M32 30 L17 48" />
          <path d="M32 30 L12 35" />
        </g>

        {/* 雷达扫描弧（右上） */}
        <path
          d="M32 30 A14.5 14.5 0 0 1 46 19.5"
          fill="none"
          stroke="#22d3ee"
          strokeWidth="2.5"
          strokeLinecap="round"
          opacity="0.9"
        />
        <circle cx="46" cy="19.5" r="2" fill="#22d3ee" opacity="0.9" />

        {/* 环绕节点 */}
        <g fill="#c4b5fd">
          <circle cx="17" cy="20" r="3" />
          <circle cx="47" cy="20" r="3" />
          <circle cx="52" cy="35" r="3" />
          <circle cx="47" cy="48" r="3" />
          <circle cx="17" cy="48" r="3" />
          <circle cx="12" cy="35" r="3" />
        </g>

        {/* 中心节点 */}
        <circle cx="32" cy="30" r="8" fill={`url(#${coreId})`} />
        <circle cx="32" cy="30" r="3" fill="#ffffff" />
      </svg>
    </span>
  );
}
