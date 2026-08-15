import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  ArrowRight,
  Cloud,
  Eye,
  EyeOff,
  HelpCircle,
  Mail,
  RefreshCw,
  Save,
  Settings2,
  ShieldCheck,
  Webhook,
} from "lucide-react";
import { api } from "@/lib/api";
import {
  Button,
  buttonVariants,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Input,
  Label,
  PageHeader,
  Select,
  Switch,
  Toast,
} from "@/components/ui";

const PROVIDERS = [
  {
    value: "cloudflare",
    label: "Cloudflare 临时邮箱",
    description: "适合自建 Worker/API；可配置域名、鉴权方式和收信路径。",
  },
  {
    value: "duckmail",
    label: "DuckMail / Mail.tm",
    description: "通用临时邮箱接口；DuckMail 可填 API Key，Mail.tm 公共接口可留空。",
  },
  {
    value: "yyds",
    label: "YYDS 临时邮箱",
    description: "需要 YYDS API Key 或 JWT，可固定已验证收信域名。",
  },
  {
    value: "mailnest",
    label: "MailNest 迈巢 Outlook",
    description: "Outlook 临时邮箱服务，需要 API Key 和项目代码。",
  },
  {
    value: "cloudmail",
    label: "CloudMail 自建邮箱",
    description: "适合自建 cloud-mail，需要站点地址、管理员账号和域名。",
  },
];
export type SettingsSection = "registration" | "tokenauth" | "mail";

const SECTION_META: Record<SettingsSection, { title: string; description: string }> = {
  registration: { title: "注册设置", description: "注册数量、代理、浏览器语言与运行方式。" },
  tokenauth: {
    title: "ProxyScrape / Resin",
    description: "ProxyScrape 注册参数与 Resin 代理池入池配置。",
  },
  mail: { title: "邮箱服务", description: "选择邮箱服务商并维护对应接口与访问凭据。" },
};
const TOKEN_MODES = [
  { value: "device_protocol", label: "协议 Device Flow" },
  { value: "device_browser", label: "浏览器 Device Flow" },
  { value: "auth_code", label: "授权码 Authorization Code" },
];
const CLOUDFLARE_AUTH_MODES = [
  { value: "none", label: "无需鉴权" },
  { value: "bearer", label: "Bearer Token" },
  { value: "x-api-key", label: "X-API-Key" },
  { value: "x-admin-auth", label: "管理员密码 X-Admin-Auth" },
  { value: "query-key", label: "URL 参数 key" },
];

function ToggleRow({
  title,
  description,
  checked,
  onCheckedChange,
}: {
  title: string;
  description?: string;
  checked: boolean;
  onCheckedChange: (value: boolean) => void;
}) {
  return (
    <div className="flex min-h-16 items-center justify-between gap-4 rounded-xl border bg-muted/35 px-3 py-3 sm:px-4">
      <div className="min-w-0">
        <div className="text-sm font-medium text-foreground">{title}</div>
        {description ? <div className="mt-0.5 text-xs leading-5 text-muted-foreground">{description}</div> : null}
      </div>
      <Switch checked={checked} onCheckedChange={onCheckedChange} label={title} />
    </div>
  );
}

function SectionIcon({ children }: { children: React.ReactNode }) {
  return (
    <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-sky-50 text-sky-600">
      {children}
    </span>
  );
}

function ConfigField({
  config,
  onFieldChange,
  label,
  field,
  type = "text",
  placeholder = "",
  helper = "",
}: {
  config: Record<string, any>;
  onFieldChange: (key: string, value: any) => void;
  label: string;
  field: string;
  type?: string;
  placeholder?: string;
  helper?: string;
}) {
  const [showSecret, setShowSecret] = useState(false);
  const isPassword = type === "password";
  return (
    <div className="min-w-0 space-y-2">
      <Label htmlFor={field}>{label}</Label>
      <div className="relative">
        <Input
          id={field}
          type={isPassword && showSecret ? "text" : type}
          inputMode={type === "number" ? "numeric" : undefined}
          autoComplete={isPassword ? "new-password" : "off"}
          className={isPassword ? "pr-10" : undefined}
          placeholder={placeholder}
          value={config[field] ?? ""}
          onChange={(event) =>
            onFieldChange(
              field,
              type === "number" && event.target.value !== ""
                ? Number(event.target.value)
                : event.target.value
            )
          }
        />
        {isPassword ? (
          <button
            type="button"
            className="absolute inset-y-0 right-0 flex w-10 items-center justify-center text-muted-foreground transition hover:text-foreground"
            aria-label={showSecret ? `隐藏${label}` : `显示${label}`}
            aria-pressed={showSecret}
            onClick={() => setShowSecret((value) => !value)}
          >
            {showSecret ? <EyeOff className="h-4 w-4" aria-hidden="true" /> : <Eye className="h-4 w-4" aria-hidden="true" />}
          </button>
        ) : null}
      </div>
      {helper ? <p className="text-xs leading-5 text-muted-foreground">{helper}</p> : null}
    </div>
  );
}

function HelpRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-0.5 sm:grid-cols-[9rem_1fr] sm:gap-3">
      <div className="font-medium text-slate-700">{label}</div>
      <div className="text-slate-600">{children}</div>
    </div>
  );
}

function Code({ children }: { children: React.ReactNode }) {
  return (
    <code className="rounded bg-slate-100 px-1 py-0.5 font-mono text-[11px] text-slate-800">
      {children}
    </code>
  );
}

function CloudflareHelp() {
  return (
    <details className="group sm:col-span-2 rounded-xl border border-sky-100 bg-sky-50/60 p-3 sm:p-4">
      <summary className="flex cursor-pointer list-none items-center gap-2 text-sm font-medium text-slate-900">
        <HelpCircle className="h-4 w-4 shrink-0 text-sky-600" aria-hidden="true" />
        配置帮助：cloudflare_temp_email 怎么填
        <span className="ml-auto text-xs font-normal text-slate-500 group-open:hidden">展开</span>
        <span className="ml-auto hidden text-xs font-normal text-slate-500 group-open:inline">收起</span>
      </summary>

      <div className="mt-3 space-y-3 text-xs leading-6">
        <p className="text-slate-600">
          下面按 <span className="font-medium">dreamhunter2333/cloudflare_temp_email</span> 自建 Worker 的官方文档说明。
          本项目走 admin 建号 + 地址 JWT 收信这一条链路。
        </p>

        <div className="space-y-2 rounded-lg bg-white/70 p-3">
          <HelpRow label="接口地址">
            Worker 根域名，如 <Code>https://mail.example.com</Code>。
            只填根地址，<span className="font-medium">不要</span>带 <Code>/api</Code> 或结尾斜杠。
          </HelpRow>
          <HelpRow label="API Key / 管理员密码">
            填后台的 <Code>ADMIN_PASSWORDS</Code>（管理员密码），会作为 <Code>x-admin-auth</Code> 发出。
            不是站点访问密码，也不是邮箱 JWT。
          </HelpRow>
          <HelpRow label="鉴权方式">
            选<span className="font-medium">「管理员密码 X-Admin-Auth」</span>。
            建号端点只认这个头；留成「无需鉴权」时只要填了密码也会自动补上，但显式选中更清楚。
          </HelpRow>
          <HelpRow label="全局访问密码">
            仅当 Worker 配了 <Code>PASSWORDS</Code>（整站私有密码）才填，对应 <Code>x-custom-auth</Code>。
            没开私有站点就留空。
          </HelpRow>
          <HelpRow label="收信域名">
            必须是后台 <Code>DOMAINS</Code> / <Code>DEFAULT_DOMAINS</Code> 里已存在的域名，只填域名本身（
            <Code>example.com</Code>），不带 <Code>@</Code>。多个用逗号分隔，会轮流使用。
          </HelpRow>
        </div>

        <div className="space-y-2 rounded-lg bg-white/70 p-3">
          <div className="font-medium text-slate-700">四个接口路径（默认值一般不用改）</div>
          <HelpRow label="创建邮箱">
            <Code>/admin/new_address</Code> — 官方 admin 建号接口，返回 <Code>address</Code> 和 <Code>jwt</Code>。
          </HelpRow>
          <HelpRow label="邮件列表">
            <Code>/api/mails</Code> — 用上一步的地址 JWT 以 <Code>Bearer</Code> 拉取。
            该接口只回原始 MIME，本项目会在本地解码后再提验证码。
            新版 Worker 若有 <Code>/api/parsed_mails</Code>（服务端已解析）也可以填，两种都兼容。
          </HelpRow>
          <HelpRow label="域名 / Token">
            <Code>/api/domains</Code>、<Code>/api/token</Code> 只给非 cloudflare_temp_email 的旧版兼容回退用。
            自建 cloudflare_temp_email 时这两项用不到，保持默认即可，填错也不影响正常流程。
          </HelpRow>
        </div>

        <div className="space-y-2 rounded-lg bg-white/70 p-3">
          <div className="font-medium text-slate-700">配置错了通常是这几种</div>
          <HelpRow label="401 / 403">
            管理员密码不对，或鉴权方式没选 X-Admin-Auth；开了私有站点却没填全局访问密码。
          </HelpRow>
          <HelpRow label="404">
            接口地址多带了 <Code>/api</Code>，或创建邮箱路径被改成了别的值。
          </HelpRow>
          <HelpRow label="建号成功但收不到码">
            邮件列表路径填错，或收信域名不在后台允许列表里（邮件根本没投递进来）。
          </HelpRow>
          <HelpRow label="域名相关报错">
            收信域名带了 <Code>@</Code>，或该域名没在 Worker 后台配置过。
          </HelpRow>
          <p className="text-slate-500">
            填完可以用页面上的连通性检查验证；它探的是建号端点，能区分「鉴权失败」和「服务不可达」。
          </p>
        </div>
      </div>
    </details>
  );
}

export function SettingsPage({ section = "registration" }: { section?: SettingsSection }) {
  const [searchParams] = useSearchParams();
  const [config, setConfig] = useState<Record<string, any>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState<{ message: string; tone?: "default" | "success" | "error" }>({
    message: "",
  });

  const showToast = (message: string, tone: "default" | "success" | "error" = "default") => {
    setToast({ message, tone });
    window.setTimeout(() => setToast({ message: "" }), 2200);
  };

  const load = async () => {
    setLoading(true);
    try {
      const data = await api.getConfig();
      const requestedProvider = section === "mail" ? String(searchParams.get("provider") || "") : "";
      const validProvider = PROVIDERS.some((item) => item.value === requestedProvider) ? requestedProvider : "";
      setConfig({ ...(data.config || {}), ...(validProvider ? { email_provider: validProvider } : {}) });
    } catch (err: any) {
      showToast(err.message || "加载配置失败", "error");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const setField = (key: string, value: any) => {
    setConfig((previous) => ({ ...previous, [key]: value }));
  };
  const fieldState = { config, onFieldChange: setField };
  const selectedProvider = PROVIDERS.find(
    (item) => item.value === (config.email_provider || "cloudflare")
  ) || PROVIDERS[0];

  const onSave = async () => {
    setSaving(true);
    try {
      const data = await api.saveConfig(config);
      setConfig(data.config || config);
      showToast(`已保存 ${data.changed?.length || 0} 项配置`, "success");
    } catch (err: any) {
      showToast(err.message || "保存失败", "error");
    } finally {
      setSaving(false);
    }
  };

  const meta = SECTION_META[section];

  return (
    <div className="space-y-5 sm:space-y-6">
      <PageHeader
        title={meta.title}
        description={meta.description}
        actions={
          <>
            <Button variant="outline" onClick={load} disabled={loading || saving}>
              <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} aria-hidden="true" />
              重新加载
            </Button>
            <Button onClick={onSave} disabled={saving || loading}>
              <Save className="h-4 w-4" aria-hidden="true" />
              {saving ? "保存中…" : "保存配置"}
            </Button>
          </>
        }
      />

      <div className="space-y-4">
        {section === "registration" ? (
        <Card>
          <CardHeader className="flex-row items-start gap-3">
            <SectionIcon><Settings2 className="h-5 w-5" aria-hidden="true" /></SectionIcon>
            <div>
              <CardTitle>基础与注册</CardTitle>
              <CardDescription>邮箱来源、代理、数量、并发和浏览器运行方式。</CardDescription>
            </div>
          </CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2 sm:col-span-2">
              <Label htmlFor="email_provider">邮箱服务商</Label>
              <Select
                id="email_provider"
                value={config.email_provider || "cloudflare"}
                onChange={(event) => setField("email_provider", event.target.value)}
              >
                {PROVIDERS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
              </Select>
              <p className="text-xs leading-5 text-muted-foreground">{selectedProvider.description}</p>
            </div>
            <div className="flex flex-col gap-3 rounded-xl border border-sky-100 bg-sky-50/70 p-3 sm:col-span-2 sm:flex-row sm:items-center sm:justify-between sm:p-4">
              <div className="flex min-w-0 items-start gap-3">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-white text-sky-600 ring-1 ring-sky-100">
                  <Mail className="h-4 w-4" aria-hidden="true" />
                </span>
                <div className="min-w-0">
                  <div className="text-sm font-medium text-slate-900">配置 {selectedProvider.label}</div>
                  <p className="mt-0.5 text-xs leading-5 text-slate-500">
                    前往邮箱服务页面填写该服务商需要的接口与凭据。
                  </p>
                </div>
              </div>
              <Link
                to={`/settings/mail?provider=${encodeURIComponent(selectedProvider.value)}`}
                className={buttonVariants({ variant: "outline", className: "w-full bg-white sm:w-auto" })}
              >
                前往设置
                <ArrowRight className="h-4 w-4" aria-hidden="true" />
              </Link>
            </div>
            <ConfigField
              {...fieldState}
              label="网络代理"
              field="proxy"
              type="password"
              placeholder="http://user:password@host:port"
              helper="支持无认证或用户名/密码认证的 HTTP(S) 代理；凭据含 @、:、/、#、% 等特殊字符时请使用 URL 百分号编码，例如 @ 写成 %40。注册浏览器与 ProxyScrape API 请求会共用此代理。"
            />
            <ConfigField {...fieldState}
              label="账号间隔（秒）"
              field="account_interval"
              placeholder="60-120"
              helper="支持固定秒数或区间；等待过程可随时停止。"
            />
            <ConfigField {...fieldState} label="注册数量" field="register_count" type="number" />
            <ConfigField {...fieldState} label="并发浏览器数" field="register_workers" type="number" />
            <ConfigField {...fieldState} label="日志级别" field="log_level" placeholder="info（普通）/ debug（详细）" />
            <div className="min-w-0 space-y-2">
              <Label htmlFor="browser_locale">浏览器界面语言</Label>
              <Select
                id="browser_locale"
                value={config.browser_locale || "en-US"}
                onChange={(event) => setField("browser_locale", event.target.value)}
              >
                <option value="en-US">English (en-US，推荐)</option>
                <option value="zh-CN">简体中文 (zh-CN)</option>
              </Select>
              <p className="text-xs leading-5 text-muted-foreground">
                固定注册页面语言，不跟随代理出口自动切换。
              </p>
            </div>
            <div className="space-y-3 sm:col-span-2">
              <ToggleRow
                title="调试模式"
                description="强制单账号，结束后保留浏览器"
                checked={!!config.debug_mode}
                onCheckedChange={(value) => setField("debug_mode", value)}
              />
              <ToggleRow
                title="无头浏览器"
                description="后台运行且不显示窗口；Camoufox 会修正常见无头指纹，但无法保证不触发站点风控"
                checked={!!config.browser_headless}
                onCheckedChange={(value) => setField("browser_headless", value)}
              />
              <ToggleRow
                title="停止时关闭浏览器"
                description="收到停止请求后清理当前浏览器实例"
                checked={!!config.close_browser_on_stop}
                onCheckedChange={(value) => setField("close_browser_on_stop", value)}
              />
            </div>
          </CardContent>
        </Card>
        ) : null}

        {/* TokenAuth：ProxyScrape 注册参数 + Resin 代理池 */}
        {section === "tokenauth" ? (
        <div className="space-y-4">
          <Card>
            <CardHeader className="flex-row items-start gap-3">
              <SectionIcon><ShieldCheck className="h-5 w-5" aria-hidden="true" /></SectionIcon>
              <div>
                <CardTitle>ProxyScrape 注册</CardTitle>
                <CardDescription>注册页、API 与账号参数；成功标准为拿到 access_token 与 AccountID 并下载代理列表。</CardDescription>
              </div>
            </CardHeader>
            <CardContent className="grid gap-4 sm:grid-cols-2">
              <ConfigField {...fieldState} label="控制台地址" field="ps_dashboard_base" placeholder="https://dashboard.proxyscrape.com/v2" />
              <ConfigField {...fieldState} label="API 地址" field="ps_api_base" placeholder="留空使用 https://dashboard.proxyscrape.com/v4" />
              <ConfigField {...fieldState} label="注册页地址" field="ps_signup_url" placeholder="留空使用 控制台地址/sign-up" />
              <ConfigField {...fieldState} label="密码长度" field="ps_password_length" type="number" helper="10–32 位，越界自动收敛" />
              <ConfigField {...fieldState} label="代理协议" field="ps_proxy_protocol" placeholder="http" />
              <ConfigField {...fieldState} label="代理格式" field="ps_proxy_format" placeholder="userpass" />
              <ConfigField {...fieldState} label="代理列表目录" field="ps_proxy_list_dir" placeholder="data/proxy_lists" />
              <ConfigField {...fieldState} label="账号有效天数" field="account_valid_days" type="number" helper="用于展示有效期" />
              <div className="space-y-3 sm:col-span-2">
                <ToggleRow
                  title="跳过注册问卷"
                  description="注册后跳过 Typeform 问卷；关闭则提交默认问卷响应"
                  checked={!!config.ps_skip_typeform}
                  onCheckedChange={(value) => setField("ps_skip_typeform", value)}
                />
                <ToggleRow
                  title="问卷使用占位响应"
                  description="问卷响应 ID 缺失时使用占位值，避免注册卡在问卷提交"
                  checked={config.ps_typeform_response_stub !== false}
                  onCheckedChange={(value) => setField("ps_typeform_response_stub", value)}
                />
              </div>
              <ConfigField {...fieldState} label="问卷表单 ID" field="ps_typeform_form_id" placeholder="vnCgUn0n" />
              <ConfigField {...fieldState} label="问卷响应 ID" field="ps_typeform_response_id" />
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex-row items-start gap-3">
              <SectionIcon><Webhook className="h-5 w-5" aria-hidden="true" /></SectionIcon>
              <div>
                <CardTitle>Resin 代理池</CardTitle>
                <CardDescription>注册成功后可选将代理列表推送为 Resin 订阅；失败不影响注册成功判定。</CardDescription>
              </div>
            </CardHeader>
            <CardContent className="grid gap-4 sm:grid-cols-2">
              <div className="sm:col-span-2">
                <ToggleRow
                  title="启用 Resin 入池"
                  description="注册成功且 Resin 未配置时不报错；配置了地址与 Token 时自动推送"
                  checked={!!config.resin_enabled_flag}
                  onCheckedChange={(value) => setField("resin_enabled_flag", value)}
                />
              </div>
              <ConfigField {...fieldState} label="Resin 地址" field="resin_base_url" placeholder="https://resin.example.com" />
              <ConfigField {...fieldState} label="鉴权 Token" field="resin_auth_token" type="password" />
              <ConfigField {...fieldState} label="会话 Cookie" field="resin_cookie" type="password" helper="可选；与 Token 二选一" />
              <ConfigField {...fieldState} label="订阅路径" field="resin_subscriptions_path" placeholder="/api/v1/subscriptions" />
              <ConfigField {...fieldState} label="请求超时（秒）" field="resin_timeout" type="number" />
              <ConfigField {...fieldState} label="代理协议" field="resin_proxy_scheme" placeholder="http" />
              <ConfigField {...fieldState} label="来源类型" field="resin_source_type" placeholder="local" />
              <ConfigField {...fieldState} label="更新间隔" field="resin_update_interval" placeholder="12h" />
              <ConfigField {...fieldState} label="临时节点驱逐延迟" field="resin_ephemeral_node_evict_delay" placeholder="72h" />
              <div className="space-y-3 sm:col-span-2">
                <ToggleRow
                  title="校验 TLS"
                  description="关闭时使用 http:// 并忽略证书校验，适合自建内网 Resin"
                  checked={!!config.resin_verify_tls}
                  onCheckedChange={(value) => setField("resin_verify_tls", value)}
                />
                <ToggleRow
                  title="临时节点"
                  description="节点按有效期标记临时，到期后由 Resin 驱逐"
                  checked={!!config.resin_ephemeral}
                  onCheckedChange={(value) => setField("resin_ephemeral", value)}
                />
                <ToggleRow
                  title="增量活跃节点"
                  description="仅更新活跃节点，减少全量推送"
                  checked={!!config.resin_incremental_alive_nodes}
                  onCheckedChange={(value) => setField("resin_incremental_alive_nodes", value)}
                />
              </div>
            </CardContent>
          </Card>
        </div>
        ) : null}

        {section === "mail" ? (
        <Card>
          <CardHeader className="flex-row items-start gap-3">
            <SectionIcon><Cloud className="h-5 w-5" aria-hidden="true" /></SectionIcon>
            <div>
              <CardTitle>邮箱服务商凭证</CardTitle>
              <CardDescription>当前选择：{selectedProvider.label}。这里只显示该服务所需字段。</CardDescription>
            </div>
          </CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-2">
            <div className="sm:col-span-2">
              <Label htmlFor="email_provider">邮箱服务商</Label>
              <Select
                id="email_provider"
                value={config.email_provider || "cloudflare"}
                onChange={(event) => setField("email_provider", event.target.value)}
              >
                {PROVIDERS.map((item) => (
                  <option key={item.value} value={item.value}>{item.label}</option>
                ))}
              </Select>
            </div>
            <div className="sm:col-span-2 rounded-xl border bg-muted/35 p-3 text-sm">
              <div className="font-medium">{selectedProvider.label}</div>
              <div className="mt-1 text-xs leading-5 text-muted-foreground">{selectedProvider.description}</div>
            </div>

            {selectedProvider.value === "duckmail" ? (
              <>
                <ConfigField {...fieldState} label="接口地址" field="duckmail_api_base" helper="DuckMail 默认 https://api.duckmail.sbs；Mail.tm 填 https://api.mail.tm" />
                <ConfigField {...fieldState} label="API Key" field="duckmail_api_key" type="password" helper="DuckMail 私有域需要；Mail.tm 公共接口可留空" />
              </>
            ) : null}

            {selectedProvider.value === "cloudflare" ? (
              <>
                <CloudflareHelp />
                <ConfigField {...fieldState} label="接口地址" field="cloudflare_api_base" placeholder="https://mail.example.com" helper="Worker 根地址，不要带 /api 或结尾斜杠" />
                <ConfigField {...fieldState} label="API Key / 管理员密码" field="cloudflare_api_key" type="password" helper="后台 ADMIN_PASSWORDS，作为 x-admin-auth 发送" />
                <div className="min-w-0 space-y-2">
                  <Label htmlFor="cloudflare_auth_mode">鉴权方式</Label>
                  <Select
                    id="cloudflare_auth_mode"
                    value={config.cloudflare_auth_mode || "none"}
                    onChange={(event) => setField("cloudflare_auth_mode", event.target.value)}
                  >
                    {CLOUDFLARE_AUTH_MODES.map((item) => (
                      <option key={item.value} value={item.value}>{item.label}</option>
                    ))}
                  </Select>
                </div>
                <ConfigField {...fieldState} label="全局访问密码" field="cloudflare_custom_auth" type="password" helper="对应 Worker PASSWORDS，发送到 X-Custom-Auth" />
                <ConfigField {...fieldState} label="收信域名" field="defaultDomains" placeholder="example.com" helper="必填，需与后台 DOMAINS 一致；多个用逗号分隔，轮流使用" />
                <ConfigField {...fieldState} label="创建邮箱接口路径" field="cloudflare_path_accounts" placeholder="/admin/new_address" helper="保持默认 /admin/new_address" />
                <ConfigField {...fieldState} label="邮件列表接口路径" field="cloudflare_path_messages" placeholder="/api/mails" helper="默认 /api/mails；新版 Worker 可填 /api/parsed_mails" />
                <ConfigField {...fieldState} label="域名接口路径" field="cloudflare_path_domains" placeholder="/api/domains" helper="仅旧版兼容回退使用，cloudflare_temp_email 用不到" />
                <ConfigField {...fieldState} label="获取 Token 接口路径" field="cloudflare_path_token" placeholder="/api/token" helper="仅旧版兼容回退使用，cloudflare_temp_email 用不到" />
              </>
            ) : null}

            {selectedProvider.value === "yyds" ? (
              <>
                <ConfigField {...fieldState} label="API Key" field="yyds_api_key" type="password" helper="API Key 与 JWT 至少填写一个" />
                <ConfigField {...fieldState} label="JWT" field="yyds_jwt" type="password" helper="填写 JWT 时优先使用 JWT 鉴权" />
                <ConfigField {...fieldState} label="固定收信域名" field="yyds_default_domain" helper="留空时自动选择已验证域名" />
              </>
            ) : null}

            {selectedProvider.value === "mailnest" ? (
              <>
                <ConfigField {...fieldState} label="API Key" field="mailnest_api_key" type="password" />
                <ConfigField {...fieldState} label="项目代码" field="mailnest_project_code" helper="默认 x-ai001" />
              </>
            ) : null}

            {selectedProvider.value === "cloudmail" ? (
              <>
                <ConfigField {...fieldState} label="站点地址" field="cloudmail_url" helper="自建 cloud-mail 根地址，不要附加 /api" />
                <ConfigField {...fieldState} label="管理员邮箱" field="cloudmail_admin_email" />
                <ConfigField {...fieldState} label="管理员密码" field="cloudmail_password" type="password" />
                <ConfigField {...fieldState} label="收信域名" field="defaultDomains" helper="多个域名可用逗号或空格分隔" />
              </>
            ) : null}
          </CardContent>
        </Card>
        ) : null}
      </div>

      <div className="sticky bottom-[calc(4.75rem+env(safe-area-inset-bottom))] z-20 rounded-2xl border bg-card/95 p-2 shadow-lg backdrop-blur lg:hidden">
        <Button className="w-full" onClick={onSave} disabled={saving || loading}>
          <Save className="h-4 w-4" aria-hidden="true" />
          {saving ? "保存中…" : "保存全部配置"}
        </Button>
      </div>

      <Toast message={toast.message} tone={toast.tone} />
    </div>
  );
}
