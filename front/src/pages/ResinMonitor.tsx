import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  CircleDot,
  Database,
  PlusCircle,
  RefreshCw,
  Settings2,
  Timer,
  Trash2,
  XCircle,
} from "lucide-react";
import { api, type ResinMonitorStatus } from "@/lib/api";
import { Badge, Button, Card, CardContent, CardDescription, CardHeader, CardTitle, PageHeader, buttonVariants } from "@/components/ui";
import { cn } from "@/lib/utils";

function StatusBadge({ monitor }: { monitor: ResinMonitorStatus }) {
  if (!monitor.running) {
    return <Badge variant="secondary">{monitor.enabled ? "已启用但未运行" : "未启用"}</Badge>;
  }
  return <Badge variant="success">运行中</Badge>;
}

function MetricCard({
  label,
  value,
  hint,
  tone = "default",
}: {
  label: string;
  value: string | number;
  hint?: string;
  tone?: "default" | "good" | "warn" | "bad";
}) {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{label}</div>
        <div
          className={cn(
            "mt-1 text-2xl font-semibold tabular-nums",
            tone === "good" && "text-emerald-700",
            tone === "warn" && "text-amber-700",
            tone === "bad" && "text-red-700"
          )}
        >
          {value}
        </div>
        {hint ? <div className="mt-0.5 text-[11px] text-muted-foreground">{hint}</div> : null}
      </CardContent>
    </Card>
  );
}

export function ResinMonitorPage() {
  const [monitor, setMonitor] = useState<ResinMonitorStatus | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [checking, setChecking] = useState(false);
  const [checkResult, setCheckResult] = useState("");

  const refresh = useCallback(async () => {
    try {
      const data = await api.resinMonitor();
      setMonitor(data.monitor);
      setError("");
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : String(reason || "状态加载失败"));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 4000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const runCheck = async () => {
    setChecking(true);
    setCheckResult("");
    try {
      const data = await api.resinMonitorCheck();
      setMonitor(data.monitor);
      setCheckResult(
        `检查完成：到期删除 ${data.result.expired} 个，补号 ${data.result.topup} 个（补号任务已提交则后台执行）`
      );
      setError("");
    } catch (reason: unknown) {
      setCheckResult("");
      setError(reason instanceof Error ? reason.message : String(reason || "手动检查失败"));
    } finally {
      setChecking(false);
    }
  };

  const running = !!monitor?.running;
  const enabled = !!monitor?.enabled;
  const configured = monitor?.resin_configured !== false;
  const target = monitor?.target_count || 0;
  const active = monitor?.active || 0;
  const gap = monitor?.gap || 0;

  return (
    <div className="mx-auto max-w-5xl space-y-5 p-4 sm:p-6">
      <PageHeader
        title="Resin 监控"
        description="Resin 账号池自动维护：到期清理、自动补号到目标数量。每 4 秒自动刷新。"
        actions={
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={() => void refresh()} disabled={loading}>
              <RefreshCw className={cn("mr-1.5 h-3.5 w-3.5", loading && "animate-spin")} aria-hidden="true" />
              刷新
            </Button>
            <Button size="sm" onClick={() => void runCheck()} disabled={checking}>
              <Activity className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" />
              {checking ? "检查中…" : "立即检查一次"}
            </Button>
          </div>
        }
      />

      {error ? (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">{error}</div>
      ) : null}
      {checkResult ? (
        <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
          {checkResult}
        </div>
      ) : null}

      {/* 运行状态 */}
      <Card>
        <CardContent className="p-4">
          <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
            <div className="flex items-center gap-2">
              <span
                className={cn(
                  "h-2.5 w-2.5 rounded-full",
                  running ? "animate-pulse bg-emerald-500" : enabled ? "bg-amber-400" : "bg-slate-300"
                )}
              />
              <span className="text-sm font-semibold">监控状态</span>
              <StatusBadge monitor={monitor ?? ({ enabled: false, running: false } as ResinMonitorStatus)} />
            </div>
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Timer className="h-4 w-4" aria-hidden="true" />
              轮询间隔 <span className="font-semibold text-foreground">{monitor?.interval ?? "—"} 秒</span>
            </div>
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <CircleDot className="h-4 w-4" aria-hidden="true" />
              上次检查 <span className="font-semibold text-foreground">{monitor?.last_checked_at || "从未"}</span>
            </div>
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Database className="h-4 w-4" aria-hidden="true" />
              Resin 配置
              <span className={cn("font-semibold", configured ? "text-emerald-700" : "text-red-700")}>
                {configured ? "已配置" : "未配置"}
              </span>
            </div>
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              到期自动删除
              <span className="font-semibold text-foreground">{monitor?.delete_expired ? "开" : "关"}</span>
            </div>
            <Link to="/settings/tokenauth" className={cn(buttonVariants({ variant: "ghost", size: "sm" }), "ml-auto")}>
              <Settings2 className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" />
              前往配置
            </Link>
          </div>
          {monitor?.summary ? (
            <div className="mt-3 rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-600">
              最近结果：<span className="font-medium text-slate-800">{monitor.summary}</span>
            </div>
          ) : null}
          {monitor?.last_error ? (
            <div className="mt-3 flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
              <span className="break-all">{monitor.last_error}</span>
            </div>
          ) : null}
        </CardContent>
      </Card>

      {!enabled ? (
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          监控未启用：请到「系统配置 → TokenAuth」打开「Resin 自动维护（监控）」开关、填写补号目标数并保存，
          然后<strong>重启 Web 服务</strong>生效。
        </div>
      ) : null}
      {!configured ? (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
          Resin 未配置：需要 resin_base_url / resin_auth_token（或 cookie），监控与入池均无法工作。
        </div>
      ) : null}

      {/* 指标 */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <MetricCard label="有效账号" value={active} hint={target > 0 ? `目标 ${target}` : "未设目标"} tone={gap > 0 ? "warn" : "good"} />
        <MetricCard label="待补缺口" value={gap} hint={gap > 0 ? "下次轮询补号" : "已达标"} tone={gap > 0 ? "warn" : "good"} />
        <MetricCard label="本轮删除" value={monitor?.last_expired ?? 0} hint="最近一次检查" />
        <MetricCard label="本轮补号" value={monitor?.last_topup ?? 0} hint="最近一次检查" />
        <MetricCard label="累计删除" value={monitor?.total_expired ?? 0} hint="自 Web 启动起" />
        <MetricCard label="累计补号" value={monitor?.total_topup ?? 0} hint="自 Web 启动起" />
      </div>

      {/* 目标进度 */}
      {target > 0 ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">补号进度</CardTitle>
            <CardDescription>
              有效账号 {active} / {target}，缺口 {gap}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="h-2.5 w-full overflow-hidden rounded-full bg-slate-100">
              <div
                className={cn(
                  "h-full rounded-full transition-all",
                  gap > 0 ? "bg-amber-400" : "bg-emerald-500"
                )}
                style={{ width: `${Math.min(100, Math.round((active / target) * 100))}%` }}
              />
            </div>
          </CardContent>
        </Card>
      ) : null}

      {/* 最近日志 */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">最近日志</CardTitle>
          <CardDescription>监控线程内部日志（最多保留 50 条）</CardDescription>
        </CardHeader>
        <CardContent>
          {!monitor || monitor.logs.length === 0 ? (
            <div className="py-6 text-center text-xs text-muted-foreground">暂无日志，监控启动后显示</div>
          ) : (
            <ul className="max-h-80 space-y-1 overflow-y-auto rounded-lg bg-slate-950 p-3 font-mono text-[11px] leading-5">
              {[...monitor.logs].reverse().map((entry, index) => (
                <li key={`${entry.time}-${index}`} className="flex gap-2">
                  <span className="shrink-0 text-slate-500">{entry.time}</span>
                  <span
                    className={cn(
                      "break-all",
                      entry.message.includes("异常") || entry.message.includes("失败")
                        ? "text-red-300"
                        : entry.message.includes("成功")
                          ? "text-emerald-300"
                          : "text-slate-200"
                    )}
                  >
                    {entry.message}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      {/* 机制说明 */}
      <div className="grid gap-3 sm:grid-cols-2">
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center gap-2 text-sm font-semibold">
              <Trash2 className="h-4 w-4 text-slate-500" aria-hidden="true" />
              到期清理
            </div>
            <p className="mt-1.5 text-xs leading-5 text-muted-foreground">
              扫描已到期（expire_at 已过）且入池成功的账号：先从 Resin 删除订阅，再删除本地记录。
              订阅删除失败则保留本地记录，下轮重试。开关：TokenAuth 配置卡「自动删除到期账号」。
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center gap-2 text-sm font-semibold">
              <PlusCircle className="h-4 w-4 text-slate-500" aria-hidden="true" />
              自动补号
            </div>
            <p className="mt-1.5 text-xs leading-5 text-muted-foreground">
              有效账号数低于目标时自动发起注册补齐缺口。注册任务运行中会跳过本轮，避免并发冲突。
              入池失败会自动重试（Resin 设置「入池失败重试次数」，默认 2 次，间隔递增）。
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
