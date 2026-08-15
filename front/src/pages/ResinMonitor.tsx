import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  Activity,
  AlertTriangle,
  CircleDot,
  Database,
  PlusCircle,
  RefreshCw,
  Search,
  Settings2,
  Timer,
  Trash2,
  XCircle,
} from "lucide-react";
import { api, type PoolItem, type PoolSnapshot, type ResinMonitorStatus } from "@/lib/api";
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

function poolStatusBadge(status: PoolItem["status"]) {
  if (status === "active") return <Badge variant="success">有效</Badge>;
  if (status === "expiring_soon") return <Badge variant="warning">即将到期</Badge>;
  if (status === "expired") return <Badge variant="destructive">已过期</Badge>;
  return <Badge variant="secondary">未知</Badge>;
}

function fmtRemaining(sec: number | null) {
  if (sec === null || sec === undefined) return "—";
  const sign = sec < 0 ? "-" : "";
  let s = Math.abs(sec);
  const d = Math.floor(s / 86400);
  s %= 86400;
  const h = Math.floor(s / 3600);
  s %= 3600;
  const m = Math.floor(s / 60);
  if (d > 0) return `${sign}${d}d ${h}h`;
  if (h > 0) return `${sign}${h}h ${m}m`;
  return `${sign}${m}m`;
}

export function ResinMonitorPage() {
  const [monitor, setMonitor] = useState<ResinMonitorStatus | null>(null);
  const [snapshot, setSnapshot] = useState<PoolSnapshot | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [poolLoading, setPoolLoading] = useState(true);
  const [checking, setChecking] = useState(false);
  const [deletingId, setDeletingId] = useState("");
  const [checkResult, setCheckResult] = useState("");
  const [q, setQ] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [resinFilter, setResinFilter] = useState("");

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

  const refreshPool = useCallback(async () => {
    try {
      const data = await api.resinPool();
      setSnapshot(data.snapshot);
      setError("");
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : String(reason || "远端状态加载失败"));
    } finally {
      setPoolLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    void refreshPool();
    const timer = window.setInterval(() => void refresh(), 4000);
    const poolTimer = window.setInterval(() => void refreshPool(), 30000);
    return () => {
      window.clearInterval(timer);
      window.clearInterval(poolTimer);
    };
  }, [refresh, refreshPool]);

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

  const deleteSubscription = async (id: string, name: string) => {
    if (!id) return;
    if (!window.confirm(`确认从 Resin 删除订阅？\n${name || id}`)) return;
    setDeletingId(id);
    try {
      await api.resinSubscriptionDelete(id);
      await refreshPool();
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : String(reason || "删除订阅失败"));
    } finally {
      setDeletingId("");
    }
  };

  const running = !!monitor?.running;
  const enabled = !!monitor?.enabled;
  const configured = monitor?.resin_configured !== false;
  const target = monitor?.target_count || 0;
  const active = monitor?.active || 0;
  const gap = monitor?.gap || 0;

  const stats = snapshot?.stats;
  const resinTotal = stats?.resin_total ?? 0;
  const inResin = stats?.in_resin ?? 0;
  const notInResin = stats?.not_in_resin ?? 0;
  const expiredStillInResin = stats?.expired_still_in_resin ?? 0;
  const orphanCount = stats?.resin_orphan ?? 0;

  const filteredItems = useMemo(() => {
    const rows = snapshot?.items ?? [];
    const ql = q.trim().toLowerCase();
    return rows.filter((it) => {
      if (statusFilter && it.status !== statusFilter) return false;
      if (resinFilter === "in" && !it.in_resin) return false;
      if (resinFilter === "out" && it.in_resin) return false;
      if (resinFilter === "expired_in" && !(it.status === "expired" && it.in_resin)) return false;
      if (ql) {
        const hay = `${it.email} ${it.resin_name}`.toLowerCase();
        if (!hay.includes(ql)) return false;
      }
      return true;
    });
  }, [snapshot, q, statusFilter, resinFilter]);

  return (
    <div className="mx-auto max-w-5xl space-y-5 p-4 sm:p-6">
      <PageHeader
        title="Resin 监控"
        description="Resin 账号池自动维护 + 远端订阅实时状态。本地状态 4 秒刷新，远端订阅 30 秒刷新。"
        actions={
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={() => void refreshPool()} disabled={poolLoading}>
              <RefreshCw className={cn("mr-1.5 h-3.5 w-3.5", poolLoading && "animate-spin")} aria-hidden="true" />
              刷新远端
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

      {/* 本地维护指标 */}
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

      {/* 远端 Resin 状态 */}
      <Card>
        <CardHeader className="flex-row items-start justify-between gap-3">
          <div>
            <CardTitle className="text-sm">Resin 远端订阅状态</CardTitle>
            <CardDescription>
              实时读取 Resin 订阅列表并与本地账号比对
              {snapshot?.resin_base_url ? ` · ${snapshot.resin_base_url}` : ""}
              {snapshot?.generated_at ? ` · 生成于 ${snapshot.generated_at}` : ""}
              {snapshot ? ` · 即将到期阈值 ${snapshot.expiring_soon_hours}h` : ""}
            </CardDescription>
          </div>
          {poolLoading ? <RefreshCw className="h-4 w-4 animate-spin text-muted-foreground" aria-hidden="true" /> : null}
        </CardHeader>
        <CardContent className="space-y-4">
          {snapshot?.resin_error ? (
            <div className="flex items-start gap-2 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
              <XCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              <span className="break-all">Resin 远端连接失败（本地数据仍显示）：{snapshot.resin_error}</span>
            </div>
          ) : null}
          {!configured ? (
            <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
              Resin 未配置（resin_base_url / resin_auth_token），无法读取远端订阅。
            </div>
          ) : null}
          {stats && resinTotal > 0 ? (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
              <MetricCard label="远端订阅" value={resinTotal} />
              <MetricCard label="已入池" value={inResin} tone="good" />
              <MetricCard label="未入池" value={notInResin} tone={notInResin > 0 ? "warn" : "default"} />
              <MetricCard
                label="过期仍在池"
                value={expiredStillInResin}
                tone={expiredStillInResin > 0 ? "bad" : "default"}
                hint={expiredStillInResin > 0 ? "需清理" : undefined}
              />
              <MetricCard label="孤儿订阅" value={orphanCount} tone={orphanCount > 0 ? "warn" : "default"} hint="本地无对应账号" />
              <MetricCard
                label="健康节点"
                value={`${stats.healthy_node_count_sum}/${stats.node_count_sum}`}
                hint={`共 ${stats.total} 个账号 · 代理文件 ${stats.proxy_file_exists}/${stats.total}`}
              />
            </div>
          ) : (
            <div className="py-4 text-center text-xs text-muted-foreground">
              {poolLoading ? "加载远端订阅中…" : "暂无远端订阅数据"}
            </div>
          )}
        </CardContent>
      </Card>

      {/* 账号 × 订阅对齐表 */}
      {snapshot && stats && stats.total > 0 ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">账号 × Resin 订阅对齐</CardTitle>
            <CardDescription>
              本地成功账号 {stats.total} 个，按邮箱前缀匹配远端订阅名
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <div className="relative min-w-[200px] flex-1">
                <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
                <input
                  value={q}
                  onChange={(event) => setQ(event.target.value)}
                  placeholder="搜索邮箱 / Resin 名…"
                  className="h-9 w-full rounded-md border border-slate-200 bg-white pl-8 pr-3 text-sm outline-none focus:border-sky-400 focus:ring-2 focus:ring-sky-100"
                />
              </div>
              <select
                value={statusFilter}
                onChange={(event) => setStatusFilter(event.target.value)}
                className="h-9 rounded-md border border-slate-200 bg-white px-2 text-sm outline-none focus:border-sky-400"
              >
                <option value="">全部状态</option>
                <option value="active">有效</option>
                <option value="expiring_soon">即将到期</option>
                <option value="expired">已过期</option>
                <option value="unknown">未知</option>
              </select>
              <select
                value={resinFilter}
                onChange={(event) => setResinFilter(event.target.value)}
                className="h-9 rounded-md border border-slate-200 bg-white px-2 text-sm outline-none focus:border-sky-400"
              >
                <option value="">Resin 全部</option>
                <option value="in">已入池</option>
                <option value="out">未入池</option>
                <option value="expired_in">过期仍在池</option>
              </select>
              <span className="text-xs text-muted-foreground">显示 {filteredItems.length} / {stats.total}</span>
            </div>
            <div className="overflow-x-auto rounded-xl border border-slate-200">
              <table className="w-full min-w-[820px] border-collapse text-left text-sm">
                <thead>
                  <tr className="border-b border-slate-200 bg-slate-50 text-[11px] uppercase tracking-wide text-slate-500">
                    <th className="px-3 py-2">状态</th>
                    <th className="px-3 py-2">邮箱</th>
                    <th className="px-3 py-2">注册 / 到期</th>
                    <th className="px-3 py-2">剩余</th>
                    <th className="px-3 py-2">Resin 订阅</th>
                    <th className="px-3 py-2">节点</th>
                    <th className="px-3 py-2">本地记录</th>
                    <th className="px-3 py-2 text-right">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredItems.map((it) => (
                    <tr key={it.id} className="border-b border-slate-100 last:border-0 hover:bg-slate-50">
                      <td className="px-3 py-2">{poolStatusBadge(it.status)}</td>
                      <td className="max-w-[220px] px-3 py-2">
                        <div className="truncate font-medium text-slate-800" title={it.email}>{it.email}</div>
                      </td>
                      <td className="px-3 py-2 text-xs text-slate-500">
                        <div className="whitespace-nowrap">{it.created_at || "—"}</div>
                        <div className="whitespace-nowrap">{it.expire_at || "—"}</div>
                      </td>
                      <td className="whitespace-nowrap px-3 py-2 font-mono text-xs">{fmtRemaining(it.remaining_sec)}</td>
                      <td className="px-3 py-2">
                        {it.in_resin ? (
                          <div className="flex items-center gap-2">
                            <span className="rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-emerald-700">
                              已入池
                            </span>
                            <span className="max-w-[140px] truncate font-mono text-xs text-slate-500" title={it.resin_name}>
                              {it.resin_name}
                            </span>
                            <span className="font-mono text-[10px] text-slate-400" title={it.resin_id}>
                              {it.resin_id.slice(0, 8)}…
                            </span>
                          </div>
                        ) : (
                          <span className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[11px] font-medium text-slate-500">
                            未入池
                          </span>
                        )}
                      </td>
                      <td className="whitespace-nowrap px-3 py-2 font-mono text-xs">
                        {it.in_resin ? (
                          <span className={cn(it.healthy_node_count > 0 ? "text-emerald-700" : "text-amber-700")}>
                            {it.healthy_node_count}/{it.node_count}
                          </span>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="px-3 py-2">
                        <span
                          className={cn(
                            "rounded-full px-2 py-0.5 text-[11px] font-medium",
                            it.resin_status === "success"
                              ? "border border-emerald-200 bg-emerald-50 text-emerald-700"
                              : it.resin_status === "failed"
                                ? "border border-red-200 bg-red-50 text-red-700"
                                : "border border-slate-200 bg-slate-50 text-slate-500"
                          )}
                        >
                          {it.resin_status === "success" ? "入池成功" : it.resin_status === "failed" ? "入池失败" : (it.resin_status || "未入池")}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-right">
                        {it.in_resin && it.resin_id ? (
                          <Button
                            variant="outline"
                            size="sm"
                            className="text-red-600 hover:bg-red-50"
                            disabled={deletingId === it.resin_id}
                            onClick={() => void deleteSubscription(it.resin_id, it.resin_name)}
                          >
                            <Trash2 className="mr-1 h-3 w-3" aria-hidden="true" />
                            删订阅
                          </Button>
                        ) : null}
                      </td>
                    </tr>
                  ))}
                  {filteredItems.length === 0 ? (
                    <tr>
                      <td colSpan={8} className="px-3 py-6 text-center text-xs text-muted-foreground">
                        无匹配记录
                      </td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      ) : null}

      {/* 孤儿订阅 */}
      {snapshot && snapshot.resin_orphans.length > 0 ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Resin 孤儿订阅</CardTitle>
            <CardDescription>远端存在但本地无对应账号（{snapshot.resin_orphans.length} 个），可手动删除</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto rounded-xl border border-slate-200">
              <table className="w-full min-w-[640px] border-collapse text-left text-sm">
                <thead>
                  <tr className="border-b border-slate-200 bg-slate-50 text-[11px] uppercase tracking-wide text-slate-500">
                    <th className="px-3 py-2">名称</th>
                    <th className="px-3 py-2">ID</th>
                    <th className="px-3 py-2">节点</th>
                    <th className="px-3 py-2">创建时间</th>
                    <th className="px-3 py-2 text-right">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {snapshot.resin_orphans.map((o) => (
                    <tr key={o.id} className="border-b border-slate-100 last:border-0 hover:bg-slate-50">
                      <td className="max-w-[220px] px-3 py-2">
                        <div className="truncate font-medium text-slate-800" title={o.name}>{o.name}</div>
                      </td>
                      <td className="px-3 py-2 font-mono text-xs text-slate-500" title={o.id}>
                        {o.id.slice(0, 12)}…
                      </td>
                      <td className="whitespace-nowrap px-3 py-2 font-mono text-xs">
                        <span className={cn(o.healthy_node_count > 0 ? "text-emerald-700" : "text-amber-700")}>
                          {o.healthy_node_count}/{o.node_count}
                        </span>
                      </td>
                      <td className="whitespace-nowrap px-3 py-2 text-xs text-slate-500">{o.created_at || "—"}</td>
                      <td className="px-3 py-2 text-right">
                        <Button
                          variant="outline"
                          size="sm"
                          className="text-red-600 hover:bg-red-50"
                          disabled={deletingId === o.id}
                          onClick={() => void deleteSubscription(o.id, o.name)}
                        >
                          <Trash2 className="mr-1 h-3 w-3" aria-hidden="true" />
                          删除
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
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
