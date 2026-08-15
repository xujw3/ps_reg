import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import {
  Braces,
  Bug,
  Camera,
  ChevronLeft,
  ChevronRight,
  Clock3,
  Copy,
  Database,
  Download,
  Eye,
  ListChecks,
  Loader2,
  LogIn,
  UploadCloud,
  MoreHorizontal,
  Power,
  RefreshCw,
  Search,
  ShieldAlert,
  Trash2,
  X,
} from "lucide-react";
import { AccountBatchActions } from "@/components/AccountBatchActions";
import { AccountEmailIcon } from "@/components/AccountEmailIcon";
import { api, type AccountRecord } from "@/lib/api";
import { cn, copyText, formatDuration, maskSecret } from "@/lib/utils";
import {
  Badge,
  Button,
  buttonVariants,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  EmptyState,
  Input,
  PageHeader,
  Select,
  Toast,
} from "@/components/ui";

function statusVariant(status: string) {
  if (status === "success") return "success" as const;
  if (status === "failure") return "destructive" as const;
  if (status === "cancelled") return "warning" as const;
  return "secondary" as const;
}

function statusLabel(status: string) {
  const labels: Record<string, string> = {
    success: "成功",
    failure: "失败",
    skipped: "跳过",
    cancelled: "已停止",
  };
  return labels[status] || status || "未知";
}
function compactBadgeVariant(status: string) {
  if (status === "success") return "success" as const;
  if (status === "failed" || status === "rejected") return "destructive" as const;
  if (status === "partial" || status === "ready" || status === "not_attempted") return "warning" as const;
  return "secondary" as const;
}

function CompactStatusBadge({ status, label }: { status: string; label: string }) {
  return (
    <Badge
      variant={compactBadgeVariant(status)}
      className="min-h-6 min-w-[58px] justify-center whitespace-nowrap rounded-md px-2 py-0 text-[11px] shadow-none"
      title={label}
    >
      {label}
    </Badge>
  );
}

function MobileStatusGrid({ item }: { item: AccountRecord }) {
  const entries = [
    ["注册", item.status, statusLabel(item.status)],
    ["账号", item.account_id || "-", item.account_id || "无 AccountID"],
    ["Resin", item.resin_status || "skipped", item.resin_status || "未入池"],
    ["代理", item.proxy_file ? "已下载" : "无", item.proxy_file || "无代理列表"],
  ];
  return (
    <div className="grid grid-cols-4 overflow-hidden rounded-lg border bg-card">
      {entries.map(([title, status, label], index) => (
        <div key={title} className={`min-w-0 px-1.5 py-1.5 text-center ${index ? "border-l" : ""}`}>
          <div className="text-[10px] leading-4 text-muted-foreground">{title}</div>
          <div className={`truncate text-[11px] font-semibold leading-4 ${
            status === "success"
              ? "text-emerald-700"
              : status === "failed" || status === "rejected"
                ? "text-red-700"
                : status === "partial" || status === "ready" || status === "not_attempted"
                  ? "text-amber-700"
                  : "text-slate-600"
          }`} title={label}>
            {label}
          </div>
        </div>
      ))}
    </div>
  );
}

function emailDisableVariant(status: string) {
  if (status === "success") return "success" as const;
  if (status === "failed") return "destructive" as const;
  if (status === "skipped_cpa" || status === "not_attempted") return "warning" as const;
  return "secondary" as const;
}

function emailDisableLabel(status: string) {
  const labels: Record<string, string> = {
    success: "已停用",
    failed: "停用失败",
    skipped_cpa: "CPA 未成功",
    feature_disabled: "功能关闭",
    unsupported_source: "非 accounts",
    not_attempted: "未执行",
    not_applicable: "不适用",
  };
  return labels[status] || status || "-";
}
function AccountDetails({
  detail,
  showPassword,
  onTogglePassword,
  onCopy,
}: {
  detail: AccountRecord;
  showPassword: boolean;
  onTogglePassword: () => void;
  onCopy: (value: string, label: string) => void;
}) {
  const fields: Array<[string, string]> = [
    ["邮箱", detail.email],
    ["密码", showPassword ? detail.password : maskSecret(detail.password)],
    ["状态", detail.status],
    ["服务商", detail.provider],
    ["access_token", detail.access_token],
    ["AccountID", detail.account_id],
    ["有效期至", detail.expire_at],
    ["账号文件", detail.account_file],
    ["代理列表", detail.proxy_file],
    ["Resin", detail.resin_status],
    ["Auth 信息", detail.auth_info],
    ["邮箱池账号 ID", detail.email_account_id],
    ["邮箱停用状态", emailDisableLabel(detail.email_disable_status)],
    ["邮箱停用时间", detail.email_disabled_at],
    ["邮箱停用错误", detail.email_disable_error],
    ["失败截图路径", detail.screenshot_path],
    ["Batch", detail.batch_id],
    ["来源", detail.source],
  ];

  return (
    <div className="space-y-4 text-sm">
      <div className="rounded-xl border border-sky-100 bg-sky-50/70 p-3">
        <div className="flex items-start gap-2">
          <AccountEmailIcon botRisk={!!detail.bot_risk} className="mt-0.5" />
          <div className="break-all font-medium text-foreground">{detail.email || "未记录邮箱"}</div>
        </div>
        <div className="mt-2 flex flex-wrap gap-2">
          <Badge variant={statusVariant(detail.status)}>{detail.status || "unknown"}</Badge>
          {detail.bot_risk ? (
            <Badge variant="warning">
              <ShieldAlert className="mr-1 h-3 w-3" aria-hidden="true" />
              风控标记
            </Badge>
          ) : null}
          {detail.resin_status === "success" ? <Badge variant="success">Resin 已入池</Badge> : null}
          {detail.resin_status === "failed" ? <Badge variant="destructive">Resin 入池失败</Badge> : null}
          <Badge variant={emailDisableVariant(detail.email_disable_status)}>
            邮箱 {emailDisableLabel(detail.email_disable_status)}
          </Badge>
        </div>
      </div>

      {detail.screenshot_url ? (
        <div className="overflow-hidden rounded-xl border border-rose-200 bg-rose-50/50">
          <div className="flex items-center gap-2 border-b border-rose-200 px-3 py-2 text-sm font-medium text-rose-800">
            <Camera className="h-4 w-4" aria-hidden="true" />
            浏览器失败现场
          </div>
          <a href={detail.screenshot_url} target="_blank" rel="noreferrer" title="在新窗口查看原图">
            <img
              src={detail.screenshot_url}
              alt={`注册失败截图 ${detail.email || detail.id}`}
              className="max-h-[28rem] w-full bg-slate-100 object-contain"
              loading="lazy"
            />
          </a>
          <div className="px-3 py-2 text-xs text-muted-foreground">点击截图可在新窗口查看原图</div>
        </div>
      ) : null}

      {detail.status === "failure" || detail.failure_reason || detail.exception_traceback ? (
        <section className="overflow-hidden rounded-xl border border-red-200 bg-red-50/60">
          <div className="flex items-center justify-between gap-3 border-b border-red-200 px-3 py-2.5">
            <div className="flex min-w-0 items-center gap-2 text-sm font-semibold text-red-800">
              <Bug className="h-4 w-4 shrink-0" aria-hidden="true" />
              <span>异常日志</span>
            </div>
            <span className="shrink-0 text-xs text-red-600">{detail.finished_at || detail.started_at || "时间未记录"}</span>
          </div>
          <div className="space-y-3 p-3">
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-[7rem_minmax(0,1fr)]">
              <div className="text-xs font-medium text-red-700">异常类型</div>
              <div className="break-words text-sm text-slate-800">
                {detail.failure_type || detail.exception_type || "未分类异常"}
              </div>
              <div className="text-xs font-medium text-red-700">异常原因</div>
              <div className="whitespace-pre-wrap break-words text-sm leading-6 text-slate-800">
                {detail.failure_reason || detail.exception_type || "未记录异常原因"}
              </div>
            </div>

            {detail.exception_traceback ? (
              <details className="group overflow-hidden rounded-lg border border-red-200 bg-slate-50/90">
                <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-3 px-3 py-2 text-sm font-medium text-red-800 [&::-webkit-details-marker]:hidden">
                  <span className="min-w-0 truncate">完整异常堆栈</span>
                  <span className="shrink-0 text-xs font-normal text-red-600 group-open:hidden">展开查看</span>
                  <span className="hidden shrink-0 text-xs font-normal text-red-600 group-open:inline">收起</span>
                </summary>
                <div className="border-t border-red-200">
                  <div className="flex items-center justify-between gap-2 border-b border-slate-200 px-3 py-1.5">
                    <span className="min-w-0 truncate text-xs text-muted-foreground">
                      {detail.exception_type || "Python 异常调用栈"}
                    </span>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="h-8 shrink-0"
                      onClick={() => onCopy(detail.exception_traceback, "异常堆栈")}
                    >
                      <Copy className="h-3.5 w-3.5" aria-hidden="true" />
                      复制
                    </Button>
                  </div>
                  <pre className="max-h-[48dvh] overflow-auto whitespace-pre-wrap break-words p-3 font-mono text-[11px] leading-5 text-slate-700 sm:text-xs">
                    {detail.exception_traceback}
                  </pre>
                </div>
              </details>
            ) : (
              <div className="rounded-lg border border-dashed border-red-200 bg-white/60 px-3 py-2 text-xs leading-5 text-red-700">
                该记录没有保存 Python 调用栈；新产生的注册异常会在这里显示完整堆栈。
              </div>
            )}
          </div>
        </section>
      ) : null}

      <div className="rounded-xl border border-slate-200 bg-slate-50/80 p-3">
        <div className="flex items-start gap-2">
          <Braces className="mt-0.5 h-4 w-4 shrink-0 text-sky-600" aria-hidden="true" />
          <div>
            <div className="text-sm font-medium text-foreground">代理列表</div>
            <p className="mt-0.5 text-xs leading-5 text-muted-foreground">
              注册成功后从 ProxyScrape 下载的 HTTP 代理列表文件。
            </p>
          </div>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          {detail.proxy_file ? (
            <a
              href={api.proxyListUrl(detail.id)}
              download
              className={buttonVariants({ variant: "outline" })}
              title={detail.proxy_file}
            >
              <Download className="h-4 w-4" aria-hidden="true" />
              下载代理列表
            </a>
          ) : (
            <span className="text-xs leading-8 text-muted-foreground">该记录没有代理列表文件</span>
          )}
        </div>
      </div>

      <div className="space-y-2">
        {fields.map(([label, value]) => (
          <div key={label} className="rounded-xl border bg-muted/30 p-3">
            <div className="mb-1 flex items-center justify-between gap-2">
              <span className="text-xs font-medium text-muted-foreground">{label}</span>
              <Button
                size="sm"
                variant="ghost"
                className="h-9 w-9 min-h-9 px-0"
                onClick={() => onCopy(String(value || ""), label)}
                aria-label={`复制${label}`}
              >
                <Copy className="h-3.5 w-3.5" aria-hidden="true" />
              </Button>
            </div>
            <div className="break-all whitespace-pre-wrap leading-6 text-foreground">{value || "-"}</div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-2 gap-2">
        <Button variant="outline" onClick={onTogglePassword}>
          <Eye className="h-4 w-4" aria-hidden="true" />
          {showPassword ? "隐藏密码" : "显示密码"}
        </Button>
        <Button
          variant="secondary"
          onClick={() => onCopy(`${detail.email}----${detail.password}`, "邮箱密码")}
        >
          <Copy className="h-4 w-4" aria-hidden="true" />
          复制账号
        </Button>
      </div>
    </div>
  );
}

export function AccountsPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const initialStatus = searchParams.get("status") || "";
  const initialKeyword = searchParams.get("q") || "";
  const initialBatchId = searchParams.get("batch_id") || "";
  const initialBotRisk = searchParams.get("bot_risk") || "";
  const [items, setItems] = useState<AccountRecord[]>([]);
  const [status, setStatus] = useState(initialStatus);
  const [emailDisableStatus, setEmailDisableStatus] = useState("");
  const [botRiskFilter, setBotRiskFilter] = useState(initialBotRisk);
  const [keyword, setKeyword] = useState(initialKeyword);
  const [batchIdFilter] = useState(initialBatchId);
  const [selected, setSelected] = useState<Record<number, boolean>>({});
  const [loading, setLoading] = useState(false);
  const [detail, setDetail] = useState<AccountRecord | null>(null);
  const [showPassword, setShowPassword] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [total, setTotal] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [selectingAll, setSelectingAll] = useState(false);
  const [batchMenuOpen, setBatchMenuOpen] = useState(false);
  const [deleteDialog, setDeleteDialog] = useState<{ ids: number[]; email: string } | null>(null);
  const [deleteBusy, setDeleteBusy] = useState<"" | "files" | "database">("");
  const [moreMenu, setMoreMenu] = useState<{
    item: AccountRecord;
    top: number;
    left: number;
  } | null>(null);
  const [toast, setToast] = useState<{ message: string; tone?: "default" | "success" | "error" }>({
    message: "",
  });

  const selectedIds = useMemo(
    () => Object.entries(selected).filter(([, value]) => value).map(([key]) => Number(key)),
    [selected]
  );
  const allVisibleSelected = items.length > 0 && items.every((item) => selected[item.id]);
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const pageNumbers = useMemo(() => {
    const count = Math.min(totalPages, 5);
    const start = Math.max(1, Math.min(page - 2, totalPages - count + 1));
    return Array.from({ length: count }, (_, index) => start + index);
  }, [page, totalPages]);

  const showToast = (message: string, tone: "default" | "success" | "error" = "default") => {
    setToast({ message, tone });
    window.setTimeout(() => setToast({ message: "" }), 2200);
  };

  const load = async (targetPage = page, targetPageSize = pageSize) => {
    setLoading(true);
    try {
      const data = await api.accounts({
        status,
        emailDisableStatus,
        q: keyword,
        batchId: batchIdFilter || undefined,
        botRisk: botRiskFilter || undefined,
        limit: targetPageSize,
        offset: (targetPage - 1) * targetPageSize,
      });
      const responseTotal = data.total;
      const hasExactTotal = responseTotal !== null && responseTotal !== undefined
        && Number.isFinite(Number(responseTotal));
      const responseCount = Number(data.count ?? data.items?.length ?? 0);
      const offset = (targetPage - 1) * targetPageSize;
      const nextHasMore = typeof data.has_more === "boolean"
        ? data.has_more
        : responseCount >= targetPageSize;
      const nextTotal = hasExactTotal
        ? Number(responseTotal)
        : Math.max(
            total,
            offset + responseCount + (nextHasMore ? 1 : 0)
          );
      const maxPage = Math.max(1, Math.ceil(nextTotal / targetPageSize));
      if (targetPage > maxPage) {
        await load(maxPage, targetPageSize);
        return;
      }
      setItems(data.items || []);
      setTotal(nextTotal);
      setHasMore(nextHasMore);
      setPage(targetPage);
      setPageSize(targetPageSize);
      if (detail) {
        setDetail((data.items || []).find((item) => item.id === detail.id) || null);
      }
    } catch (err: any) {
      showToast(err.message || "加载失败", "error");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!detail) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setDetail(null);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [detail]);

  useEffect(() => {
    if (!deleteDialog) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !deleteBusy) setDeleteDialog(null);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [deleteDialog, deleteBusy]);

  useEffect(() => {
    if (!moreMenu) return;
    const close = () => setMoreMenu(null);
    window.addEventListener("resize", close);
    window.addEventListener("scroll", close, true);
    return () => {
      window.removeEventListener("resize", close);
      window.removeEventListener("scroll", close, true);
    };
  }, [moreMenu]);

  const toggleAll = (checked: boolean) => {
    setSelected((previous) => {
      const next = { ...previous };
      for (const item of items) {
        if (checked) next[item.id] = true;
        else delete next[item.id];
      }
      return next;
    });
  };

  const selectAllFiltered = async () => {
    setSelectingAll(true);
    try {
      const result = await api.accountIds({
        status,
        emailDisableStatus,
        q: keyword,
        batchId: batchIdFilter || undefined,
        botRisk: botRiskFilter || undefined,
      });
      setSelected(Object.fromEntries((result.ids || []).map((id) => [id, true])));
      showToast(`已选择当前筛选结果 ${result.total} 个账号`, "success");
    } catch (err: any) {
      showToast(err.message || "全选筛选结果失败", "error");
    } finally {
      setSelectingAll(false);
    }
  };

  const clearSelection = () => {
    setSelected({});
    setBatchMenuOpen(false);
  };

  const onCopy = async (value: string, label: string) => {
    const ok = await copyText(value);
    showToast(ok ? `已复制${label}` : "复制失败", ok ? "success" : "error");
  };

  const openDeleteDialog = (ids = selectedIds) => {
    if (!ids.length) {
      showToast("请先选择记录", "error");
      return;
    }
    const onlyItem = ids.length === 1 ? items.find((item) => item.id === ids[0]) : null;
    setBatchMenuOpen(false);
    setMoreMenu(null);
    setDeleteDialog({ ids: [...ids], email: onlyItem?.email || "" });
  };

  const executeDelete = async (deleteFiles: boolean) => {
    if (!deleteDialog?.ids.length) return;
    setDeleteBusy(deleteFiles ? "files" : "database");
    const ids = [...deleteDialog.ids];
    const deletedIdSet = new Set(ids);
    try {
      const result = await api.deleteAccounts(ids, deleteFiles);
      const fileErrorSuffix = result.file_errors.length
        ? `，${result.file_errors.length} 个文件处理失败`
        : "";
      showToast(
        deleteFiles
          ? `已删除 ${result.deleted} 条记录和 ${result.deleted_files} 个真实文件${fileErrorSuffix}`
          : `已删除 ${result.deleted} 条数据库记录，真实文件已保留`,
        result.file_errors.length ? "error" : "success"
      );
      setSelected((previous) => {
        const next = { ...previous };
        for (const id of ids) delete next[id];
        return next;
      });
      setBatchMenuOpen(false);
      setMoreMenu(null);
      setDetail((current) => current && deletedIdSet.has(current.id) ? null : current);
      setDeleteDialog(null);
      await load(page, pageSize);
    } catch (err: any) {
      showToast(err.message || "删除失败", "error");
    } finally {
      setDeleteBusy("");
    }
  };

  const openMoreMenu = (item: AccountRecord, button: HTMLButtonElement) => {
    const rect = button.getBoundingClientRect();
    const menuWidth = 224;
    const menuHeight = 172;
    const left = Math.min(Math.max(rect.right - menuWidth, 8), window.innerWidth - menuWidth - 8);
    const top = rect.bottom + menuHeight > window.innerHeight
      ? Math.max(8, rect.top - menuHeight - 6)
      : rect.bottom + 6;
    setMoreMenu({ item, top, left });
  };

  const MoreButton = ({ item, className = "" }: { item: AccountRecord; className?: string }) => (
    <Button
      size="sm"
      variant="outline"
      className={className}
      onClick={(event) => openMoreMenu(item, event.currentTarget)}
      aria-haspopup="menu"
      aria-expanded={moreMenu?.item.id === item.id}
    >
      <MoreHorizontal className="h-4 w-4" aria-hidden="true" />
      更多
    </Button>
  );

  const MoreMenuContent = ({ item }: { item: AccountRecord }) => {
    return (
      <div role="menu" className="space-y-1">
        {item.proxy_file ? (
          <a
            href={api.proxyListUrl(item.id)}
            download
            className="flex min-h-10 items-center gap-2 rounded-lg px-3 text-sm font-medium hover:bg-muted"
            onClick={() => setMoreMenu(null)}
          >
            <Download className="h-4 w-4" aria-hidden="true" />
            下载代理列表
          </a>
        ) : (
          <span
            className="flex min-h-10 cursor-not-allowed items-center gap-2 rounded-lg px-3 text-sm text-muted-foreground opacity-45"
            title="该账号没有代理列表文件"
          >
            <Download className="h-4 w-4" aria-hidden="true" />
            无代理列表
          </span>
        )}
        <button
          type="button"
          role="menuitem"
          className="flex min-h-10 w-full items-center gap-2 rounded-lg px-3 text-left text-sm font-medium hover:bg-muted"
          onClick={() => {
            setMoreMenu(null);
            void onCopy(`${item.email}----${item.password}`, "邮箱密码");
          }}
        >
          <Copy className="h-4 w-4" aria-hidden="true" />
          复制账号
        </button>
      </div>
    );
  };

  return (
    <div className="space-y-5 sm:space-y-6">
      <PageHeader
        title="账号管理"
        description="集中筛选账号、查看注册状态与代理列表；选中账号后可批量删除。"
        actions={
          <>
            <Button variant="outline" onClick={() => void load(page, pageSize)} disabled={loading}>
              <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} aria-hidden="true" />
              刷新
            </Button>
            <AccountBatchActions
              selectedCount={selectedIds.length}
              busy={!!deleteBusy}
              menuOpen={batchMenuOpen}
              onToggleMenu={() => setBatchMenuOpen((open) => !open)}
              onCloseMenu={() => setBatchMenuOpen(false)}
              onDelete={() => {
                setBatchMenuOpen(false);
                openDeleteDialog(selectedIds);
              }}
            />
          </>
        }
      />

      {batchIdFilter ? (
        <div className="rounded-xl border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-900">
          当前按批次筛选：<span className="font-mono text-xs sm:text-sm">{batchIdFilter}</span>
          <Link to="/accounts" className="ml-3 text-sky-700 underline-offset-2 hover:underline">清除</Link>
        </div>
      ) : null}
      {selectedIds.length ? (
        <div className="flex flex-col gap-2 rounded-xl border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-900 sm:flex-row sm:items-center sm:justify-between">
          <div>
            已选择 <strong className="tabular-nums">{selectedIds.length}</strong> 个账号
            {selectedIds.length === total && total > items.length ? "（当前筛选结果全部）" : allVisibleSelected ? "（当前页全部）" : ""}
          </div>
          <div className="flex flex-wrap gap-2">
            {selectedIds.length < total ? (
              <Button size="sm" variant="outline" disabled={selectingAll || loading} onClick={() => void selectAllFiltered()}>
                {selectingAll ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <ListChecks className="h-4 w-4" aria-hidden="true" />}
                选择全部 {total} 条
              </Button>
            ) : null}
            <Button size="sm" variant="ghost" onClick={clearSelection}>取消选择</Button>
          </div>
        </div>
      ) : null}
      <Card>
        <CardContent className="space-y-3 p-4">
          <div className="grid gap-3 sm:grid-cols-3">
            <Select
              value={status}
              onChange={(e) => {
                setStatus(e.target.value);
                setSelected({});
              }}
              aria-label="按状态筛选"
            >
              <option value="">全部状态</option>
              <option value="success">success</option>
              <option value="failure">failure</option>
              <option value="skipped">skipped</option>
              <option value="cancelled">cancelled</option>
            </Select>
            <Select
              value={emailDisableStatus}
              onChange={(e) => {
                setEmailDisableStatus(e.target.value);
                setSelected({});
              }}
              aria-label="按邮箱停用状态筛选"
            >
              <option value="">全部停用状态</option>
              <option value="success">已停用</option>
              <option value="failed">停用失败</option>
              <option value="skipped_cpa">CPA 未成功</option>
              <option value="feature_disabled">功能关闭</option>
              <option value="unsupported_source">非 accounts</option>
              <option value="not_attempted">未执行</option>
              <option value="not_applicable">不适用</option>
            </Select>
            <Select
              value={botRiskFilter}
              onChange={(e) => {
                setBotRiskFilter(e.target.value);
                setSelected({});
              }}
              aria-label="按风控标记筛选"
            >
              <option value="">不限</option>
              <option value="1">异常账号</option>
              <option value="0">正常账号</option>
              <option value="unknown">未检查 / 未知</option>
            </Select>
          </div>
          <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto]">
            <div className="relative min-w-0">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
              <Input
                className="pl-9"
                type="search"
                placeholder="搜索邮箱、服务商、失败原因或 Batch"
                value={keyword}
                onChange={(e) => {
                  setKeyword(e.target.value);
                  setSelected({});
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    setSelected({});
                    void load(1, pageSize);
                  }
                }}
                aria-label="搜索账号记录"
              />
            </div>
            <Button
              onClick={() => {
                setSelected({});
                void load(1, pageSize);
              }}
              disabled={loading}
            >
              <Search className="h-4 w-4" aria-hidden="true" />
              查询
            </Button>
          </div>
        </CardContent>
      </Card>

      <div>
        <Card className="min-w-0 overflow-hidden">
          <CardHeader className="flex-row items-center justify-between gap-3">
            <div>
              <CardTitle>注册记录</CardTitle>
              <CardDescription>
                共 {total} 条，第 {page} / {totalPages} 页
                {selectedIds.length ? `，已选 ${selectedIds.length} 条` : ""}。
              </CardDescription>
            </div>
            <div className="flex flex-wrap items-center justify-end gap-1.5">
              <label className="flex min-h-10 cursor-pointer items-center gap-2 rounded-lg px-2 text-xs text-muted-foreground hover:bg-muted">
                <input
                  type="checkbox"
                  checked={allVisibleSelected}
                  onChange={(e) => toggleAll(e.target.checked)}
                />
                本页
              </label>
              <Button size="sm" variant="ghost" disabled={selectingAll || loading || !total} onClick={() => void selectAllFiltered()}>
                {selectingAll ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : null}
                全部 {total} 条
              </Button>
            </div>
          </CardHeader>
          <CardContent className="p-0">
            {items.length === 0 ? (
              <div className="p-4 sm:p-6">
                <EmptyState title="暂无账号记录" description="启动注册后，成功或失败结果会显示在这里。" />
              </div>
            ) : (
              <>
                <div className="divide-y xl:hidden">
                  {items.map((item) => (
                    <article key={item.id} className="space-y-3 p-4">
                      <div className="flex items-start gap-3">
                        <label className="flex h-11 w-8 shrink-0 cursor-pointer items-center justify-center" aria-label={`选择 ${item.email}`}>
                          <input
                            type="checkbox"
                            checked={!!selected[item.id]}
                            onChange={(e) =>
                              setSelected((prev) => ({ ...prev, [item.id]: e.target.checked }))
                            }
                          />
                        </label>
                        <div className="min-w-0 flex-1">
                          <div className="flex items-start gap-2">
                            <AccountEmailIcon botRisk={!!item.bot_risk} className="mt-1" />
                            <div className="break-all font-medium leading-6 text-foreground">{item.email || "-"}</div>
                          </div>
                          <div className="mt-2 space-y-2">
                            <MobileStatusGrid item={item} />
                            <div className="flex justify-end">
                              <Badge variant={emailDisableVariant(item.email_disable_status)}>
                                <Power className="mr-1 h-3 w-3" aria-hidden="true" />
                                邮箱 {emailDisableLabel(item.email_disable_status)}
                              </Badge>
                            </div>
                          </div>
                        </div>
                      </div>

                      <div className="grid grid-cols-2 gap-2 rounded-xl bg-muted/40 p-3 text-xs leading-5 text-muted-foreground">
                        <div>
                          <span className="block">服务商</span>
                          <strong className="block truncate font-medium text-foreground">{item.provider || "-"}</strong>
                        </div>
                        <div>
                          <span className="block">耗时</span>
                          <strong className="block font-medium text-foreground">{formatDuration(item.duration_seconds)}</strong>
                        </div>
                        <div className="col-span-2 flex items-start gap-1.5 border-t pt-2">
                          <Clock3 className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                          <span className="break-all">{item.finished_at || "未记录完成时间"}</span>
                        </div>
                      </div>

                      <div className="grid grid-cols-2 gap-2">
                        <Button variant="outline" onClick={() => setDetail(item)}>
                          查看
                          <ChevronRight className="h-4 w-4" aria-hidden="true" />
                        </Button>
                        <MoreButton item={item} className="w-full" />
                      </div>
                    </article>
                  ))}
                </div>

                <div className="hidden max-h-[720px] overflow-auto bg-white xl:block">
                  <table className="w-full min-w-[1040px] border-collapse text-left text-sm">
                    <thead className="sticky top-0 z-10 border-y border-slate-200 bg-slate-50/95 backdrop-blur">
                      <tr className="text-xs font-medium text-muted-foreground">
                        <th className="w-12 px-4 py-2">
                          <input
                            type="checkbox"
                            checked={allVisibleSelected}
                            onChange={(e) => toggleAll(e.target.checked)}
                            aria-label="全选当前记录"
                          />
                        </th>
                        <th className="px-3 py-2">账号</th>
                        <th className="w-[82px] px-2 py-2 text-center">注册</th>
                        <th className="w-[110px] px-2 py-2 text-center">AccountID</th>
                        <th className="w-[82px] px-2 py-2 text-center">代理</th>
                        <th className="w-[82px] px-2 py-2 text-center">Resin</th>
                        <th className="w-[98px] px-2 py-2 text-center">邮箱状态</th>
                        <th className="px-3 py-2">服务商</th>
                        <th className="px-3 py-2">耗时</th>
                        <th className="sticky right-0 z-20 w-[170px] bg-slate-50/95 px-3 py-2 text-center backdrop-blur">操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {items.map((item) => (
                        <tr
                          key={item.id}
                          className="group"
                        >
                          <td className={`border-b border-slate-100 px-4 py-3 transition-colors ${detail?.id === item.id ? "bg-sky-50" : "bg-white group-hover:bg-slate-50"}`}>
                            <input
                              type="checkbox"
                              checked={!!selected[item.id]}
                              onChange={(e) =>
                                setSelected((prev) => ({ ...prev, [item.id]: e.target.checked }))
                              }
                              aria-label={`选择 ${item.email}`}
                            />
                          </td>
                          <td className={`max-w-[270px] border-b border-slate-100 px-3 py-3 transition-colors ${detail?.id === item.id ? "bg-sky-50" : "bg-white group-hover:bg-slate-50"}`}>
                            <div className="flex min-w-0 items-center gap-2.5">
                              <span
                                className={cn(
                                  "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ring-1",
                                  item.bot_risk
                                    ? "bg-amber-50 text-amber-600 ring-amber-100"
                                    : "bg-sky-50 text-sky-600 ring-sky-100",
                                )}
                              >
                                <AccountEmailIcon
                                  botRisk={!!item.bot_risk}
                                  className={item.bot_risk ? "text-amber-600" : "text-sky-600"}
                                />
                              </span>
                              <div className="min-w-0">
                                <div className="truncate font-medium text-foreground" title={item.email}>{item.email || "-"}</div>
                                <div className="mt-0.5 truncate text-[11px] text-muted-foreground">{item.finished_at || "未记录时间"}</div>
                              </div>
                            </div>
                          </td>
                          <td className={`border-b border-slate-100 px-2 py-3 text-center transition-colors ${detail?.id === item.id ? "bg-sky-50" : "bg-white group-hover:bg-slate-50"}`}>
                            <CompactStatusBadge status={item.status} label={statusLabel(item.status)} />
                          </td>
                          <td className={`border-b border-slate-100 px-2 py-3 text-center transition-colors ${detail?.id === item.id ? "bg-sky-50" : "bg-white group-hover:bg-slate-50"}`}>
                            <span className="block max-w-[110px] truncate text-xs font-medium text-slate-700" title={item.account_id || ""}>
                              {item.account_id || "-"}
                            </span>
                          </td>
                          <td className={`border-b border-slate-100 px-2 py-3 text-center transition-colors ${detail?.id === item.id ? "bg-sky-50" : "bg-white group-hover:bg-slate-50"}`}>
                            {item.proxy_file ? (
                              <a
                                href={api.proxyListUrl(item.id)}
                                download
                                className="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-white px-2 py-1 text-[11px] font-medium text-slate-700 hover:bg-slate-50"
                                title={item.proxy_file}
                              >
                                <Download className="h-3 w-3" aria-hidden="true" />
                                下载
                              </a>
                            ) : (
                              <span className="text-[11px] text-muted-foreground">无</span>
                            )}
                          </td>
                          <td className={`border-b border-slate-100 px-2 py-3 text-center transition-colors ${detail?.id === item.id ? "bg-sky-50" : "bg-white group-hover:bg-slate-50"}`}>
                            <CompactStatusBadge status={item.resin_status || "skipped"} label={item.resin_status || "未入池"} />
                          </td>
                          <td className={`border-b border-slate-100 px-2 py-3 text-center transition-colors ${detail?.id === item.id ? "bg-sky-50" : "bg-white group-hover:bg-slate-50"}`}>
                            <Badge
                              variant={emailDisableVariant(item.email_disable_status)}
                              className="min-h-6 min-w-[62px] justify-center whitespace-nowrap rounded-md px-2 py-0 text-[11px] shadow-none"
                            >
                              {emailDisableLabel(item.email_disable_status)}
                            </Badge>
                            {item.email_disable_error ? (
                              <div
                                className="mt-1 max-w-[90px] truncate text-[10px] text-red-600"
                                title={item.email_disable_error}
                              >
                                {item.email_disable_error}
                              </div>
                            ) : null}
                          </td>
                          <td className={`border-b border-slate-100 px-3 py-3 text-muted-foreground transition-colors ${detail?.id === item.id ? "bg-sky-50" : "bg-white group-hover:bg-slate-50"}`}>
                            <span className="inline-flex rounded-md bg-slate-100 px-2 py-1 text-xs font-medium text-slate-600">{item.provider || "-"}</span>
                          </td>
                          <td className={`border-b border-slate-100 px-3 py-3 tabular-nums text-muted-foreground transition-colors ${detail?.id === item.id ? "bg-sky-50" : "bg-white group-hover:bg-slate-50"}`}>{formatDuration(item.duration_seconds)}</td>
                          <td className={`sticky right-0 z-[5] border-b border-slate-100 px-3 py-3 shadow-[-10px_0_18px_-18px_rgba(15,23,42,0.3)] transition-colors ${detail?.id === item.id ? "bg-sky-50" : "bg-white group-hover:bg-slate-50"}`}>
                            <div className="flex items-center justify-center gap-1.5">
                              <Button size="sm" variant="outline" onClick={() => setDetail(item)}>
                                查看
                              </Button>
                              <MoreButton item={item} />
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="flex flex-col gap-3 border-t px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
                  <div className="flex items-center gap-2 text-xs text-muted-foreground">
                    <span>每页</span>
                    <Select
                      className="h-9 min-h-9 w-20 py-1"
                      value={String(pageSize)}
                      onChange={(event) => void load(1, Number(event.target.value))}
                      aria-label="每页记录数"
                    >
                      <option value="50">50</option>
                      <option value="100">100</option>
                      <option value="200">200</option>
                      <option value="500">500</option>
                      <option value="1000">1000</option>
                    </Select>
                    <span>条，共 {total} 条</span>
                  </div>
                  <div className="flex items-center justify-between gap-2 sm:justify-end">
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={loading || page <= 1}
                      onClick={() => void load(page - 1, pageSize)}
                    >
                      <ChevronLeft className="h-4 w-4" aria-hidden="true" />
                      上一页
                    </Button>
                    <span className="min-w-16 text-center text-xs font-medium text-muted-foreground sm:hidden">
                      {page} / {totalPages}
                    </span>
                    <div className="hidden items-center gap-1 sm:flex" aria-label="页码">
                      {pageNumbers.map((pageNumber) => (
                        <Button
                          key={pageNumber}
                          size="sm"
                          variant={pageNumber === page ? "default" : "outline"}
                          className="h-9 min-h-9 w-9 px-0"
                          disabled={loading}
                          onClick={() => void load(pageNumber, pageSize)}
                          aria-current={pageNumber === page ? "page" : undefined}
                        >
                          {pageNumber}
                        </Button>
                      ))}
                    </div>
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={loading || !hasMore}
                      onClick={() => void load(page + 1, pageSize)}
                    >
                      下一页
                      <ChevronRight className="h-4 w-4" aria-hidden="true" />
                    </Button>
                  </div>
                </div>
              </>
            )}
          </CardContent>
        </Card>

      </div>

      {moreMenu ? (
        <>
          <button
            type="button"
            className="fixed inset-0 z-[75] hidden cursor-default bg-transparent xl:block"
            onClick={() => setMoreMenu(null)}
            aria-label="关闭更多操作"
          />
          <div
            className="fixed z-[76] hidden w-56 rounded-xl border bg-card p-2 shadow-2xl xl:block"
            style={{ top: moreMenu.top, left: moreMenu.left }}
          >
            <MoreMenuContent item={moreMenu.item} />
          </div>
          <div
            className="fixed inset-0 z-[75] flex items-end bg-slate-950/45 xl:hidden"
            onMouseDown={(event) => {
              if (event.target === event.currentTarget) setMoreMenu(null);
            }}
          >
            <section className="w-full rounded-t-3xl bg-card px-4 pb-[calc(1rem+env(safe-area-inset-bottom))] pt-3 shadow-2xl">
              <div className="mx-auto mb-3 h-1.5 w-12 rounded-full bg-slate-300" />
              <div className="mb-2 flex items-center justify-between gap-3 px-1">
                <div className="min-w-0">
                  <div className="font-medium">更多操作</div>
                  <div className="truncate text-xs text-muted-foreground">{moreMenu.item.email}</div>
                </div>
                <Button size="icon" variant="ghost" onClick={() => setMoreMenu(null)} aria-label="关闭更多操作">
                  <X className="h-5 w-5" aria-hidden="true" />
                </Button>
              </div>
              <MoreMenuContent item={moreMenu.item} />
            </section>
          </div>
        </>
      ) : null}

      {detail ? (
        <div
          className="fixed inset-0 z-[70] flex items-end bg-slate-950/50 sm:items-center sm:justify-center sm:p-6"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setDetail(null);
          }}
        >
          <section
            role="dialog"
            aria-modal="true"
            aria-labelledby="account-detail-title"
            className="max-h-[92dvh] w-full overflow-hidden rounded-t-3xl bg-card shadow-2xl sm:max-w-4xl sm:rounded-3xl"
          >
            <div className="mx-auto mt-2 h-1.5 w-12 rounded-full bg-slate-300" />
            <header className="sticky top-0 z-10 flex items-center justify-between gap-3 border-b bg-card px-4 py-3">
              <div className="min-w-0">
                <h2 id="account-detail-title" className="font-semibold text-foreground">账号详情</h2>
                <p className="truncate text-xs text-muted-foreground">{detail.email || "未记录邮箱"}</p>
              </div>
              <Button size="icon" variant="ghost" onClick={() => setDetail(null)} aria-label="关闭账号详情">
                <X className="h-5 w-5" aria-hidden="true" />
              </Button>
            </header>
            <div className="max-h-[calc(92dvh-74px)] overflow-y-auto px-4 pb-[calc(1.5rem+env(safe-area-inset-bottom))] pt-4">
              <AccountDetails
                detail={detail}
                showPassword={showPassword}
                onTogglePassword={() => setShowPassword((value) => !value)}
                onCopy={onCopy}
              />
            </div>
          </section>
        </div>
      ) : null}

      {deleteDialog ? (
        <div
          className="fixed inset-0 z-[100] flex items-end bg-slate-950/55 sm:items-center sm:justify-center sm:p-6"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget && !deleteBusy) setDeleteDialog(null);
          }}
        >
          <section
            role="dialog"
            aria-modal="true"
            aria-labelledby="delete-account-title"
            className="w-full overflow-hidden rounded-t-3xl bg-card shadow-2xl sm:max-w-lg sm:rounded-3xl"
          >
            <div className="mx-auto mt-2 h-1.5 w-12 rounded-full bg-slate-300 sm:hidden" />
            <header className="flex items-start justify-between gap-3 border-b px-4 py-4 sm:px-5">
              <div className="min-w-0">
                <h2 id="delete-account-title" className="font-semibold text-foreground">
                  删除{deleteDialog.ids.length === 1 ? "账号" : `选中的 ${deleteDialog.ids.length} 个账号`}
                </h2>
                <p className="mt-1 break-all text-xs leading-5 text-muted-foreground">
                  {deleteDialog.email || "请选择是否同时清理这些账号关联的真实文件。"}
                </p>
              </div>
              <Button
                size="icon"
                variant="ghost"
                className="shrink-0"
                onClick={() => setDeleteDialog(null)}
                disabled={!!deleteBusy}
                aria-label="关闭删除确认"
              >
                <X className="h-5 w-5" aria-hidden="true" />
              </Button>
            </header>

            <div className="space-y-3 px-4 py-4 sm:px-5">
              <button
                type="button"
                className="flex min-h-20 w-full items-start gap-3 rounded-2xl border border-red-200 bg-red-50 p-4 text-left transition hover:border-red-300 hover:bg-red-100 disabled:cursor-not-allowed disabled:opacity-50"
                onClick={() => void executeDelete(true)}
                disabled={!!deleteBusy}
              >
                {deleteBusy === "files" ? (
                  <Loader2 className="mt-0.5 h-5 w-5 shrink-0 animate-spin text-red-700" aria-hidden="true" />
                ) : (
                  <Trash2 className="mt-0.5 h-5 w-5 shrink-0 text-red-700" aria-hidden="true" />
                )}
                <span className="min-w-0">
                  <span className="block font-semibold text-red-900">删除数据库记录和真实文件</span>
                  <span className="mt-1 block text-xs leading-5 text-red-700">
                    同时清理账号文件、授权 JSON、失败截图及相关汇总记录。
                  </span>
                </span>
              </button>

              <button
                type="button"
                className="flex min-h-20 w-full items-start gap-3 rounded-2xl border bg-card p-4 text-left transition hover:border-slate-300 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
                onClick={() => void executeDelete(false)}
                disabled={!!deleteBusy}
              >
                {deleteBusy === "database" ? (
                  <Loader2 className="mt-0.5 h-5 w-5 shrink-0 animate-spin text-primary" aria-hidden="true" />
                ) : (
                  <Database className="mt-0.5 h-5 w-5 shrink-0 text-primary" aria-hidden="true" />
                )}
                <span className="min-w-0">
                  <span className="block font-semibold text-foreground">仅删除数据库记录</span>
                  <span className="mt-1 block text-xs leading-5 text-muted-foreground">
                    保留 data 目录中的账号文件、授权 JSON 和失败截图。
                  </span>
                </span>
              </button>
            </div>

            <footer className="border-t px-4 pb-[calc(1rem+env(safe-area-inset-bottom))] pt-3 sm:px-5 sm:pb-4">
              <Button
                variant="outline"
                className="w-full"
                onClick={() => setDeleteDialog(null)}
                disabled={!!deleteBusy}
              >
                取消
              </Button>
            </footer>
          </section>
        </div>
      ) : null}

      <Toast message={toast.message} tone={toast.tone} />
    </div>
  );
}
