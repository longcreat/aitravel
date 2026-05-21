import { CheckCircle2, Loader2, Plug, Trash2, TriangleAlert } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import {
  ConnectorState,
  ConnectorStatus,
  connectorsApi,
} from "@/features/connectors/api/connectors.api";
import { Button, ConfirmDialog, PageBackButton, useToast } from "@/shared/ui";
import { HttpError } from "@/shared/lib/http";

interface StatusBadge {
  label: string;
  className: string;
  icon?: React.ReactNode;
}

const STATUS_BADGES: Record<ConnectorStatus, StatusBadge> = {
  connected: {
    label: "已连接",
    className: "bg-emerald-50 text-emerald-700",
    icon: <CheckCircle2 className="h-3.5 w-3.5" />,
  },
  pending: {
    label: "授权中",
    className: "bg-amber-50 text-amber-700",
    icon: <Loader2 className="h-3.5 w-3.5 animate-spin" />,
  },
  expired: {
    label: "已过期",
    className: "bg-orange-50 text-orange-700",
    icon: <TriangleAlert className="h-3.5 w-3.5" />,
  },
  revoked: {
    label: "已断开",
    className: "bg-slate-100 text-slate-600",
  },
  failed: {
    label: "授权失败",
    className: "bg-rose-50 text-rose-700",
    icon: <TriangleAlert className="h-3.5 w-3.5" />,
  },
  disconnected: {
    label: "未连接",
    className: "bg-slate-100 text-slate-500",
  },
};

function isConnected(status: ConnectorStatus): boolean {
  return status === "connected";
}

export function ConnectorsPage() {
  const navigate = useNavigate();
  const { toast } = useToast();
  const [searchParams, setSearchParams] = useSearchParams();
  const [connectors, setConnectors] = useState<ConnectorState[]>([]);
  const [loading, setLoading] = useState(true);
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [disconnectTarget, setDisconnectTarget] = useState<ConnectorState | null>(null);

  const refresh = useCallback(async () => {
    try {
      const response = await connectorsApi.list();
      setConnectors(response.connectors);
    } catch (error) {
      const message =
        error instanceof HttpError ? error.message : "无法读取应用列表，请稍后重试。";
      toast({ title: "加载失败", description: message, variant: "destructive" });
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // 处理 OAuth 回调参数
  useEffect(() => {
    const status = searchParams.get("connector_status");
    const connectorId = searchParams.get("connector_id");
    const errorMessage = searchParams.get("connector_error");

    if (!status && !connectorId && !errorMessage) {
      return;
    }

    if (status === "connected" && connectorId) {
      const connector = connectors.find((item) => item.id === connectorId);
      toast({
        title: "授权成功",
        description: connector ? `${connector.display_name} 已连接。` : "应用已连接。",
      });
    } else if (status && status !== "connected") {
      toast({
        title: "授权未完成",
        description: errorMessage ?? "请重新发起授权。",
        variant: "destructive",
      });
    }

    const next = new URLSearchParams(searchParams);
    next.delete("connector_status");
    next.delete("connector_id");
    next.delete("connector_error");
    setSearchParams(next, { replace: true });
    void refresh();
  }, [searchParams, setSearchParams, toast, refresh, connectors]);

  function handleBack() {
    if (window.history.length > 1) {
      navigate(-1);
      return;
    }
    navigate("/profile", { replace: true });
  }

  async function handleConnect(connector: ConnectorState) {
    setPendingId(connector.id);
    try {
      const { authorize_url } = await connectorsApi.startAuthorization(connector.id);
      window.location.href = authorize_url;
    } catch (error) {
      const message =
        error instanceof HttpError ? error.message : "授权请求失败，请稍后重试。";
      toast({ title: "授权失败", description: message, variant: "destructive" });
      setPendingId(null);
    }
  }

  async function handleDisconnect(connector: ConnectorState) {
    setPendingId(connector.id);
    try {
      const updated = await connectorsApi.disconnect(connector.id);
      setConnectors((prev) =>
        prev.map((item) => (item.id === updated.id ? updated : item)),
      );
      toast({
        title: "已断开",
        description: `${connector.display_name} 的授权已撤销。`,
      });
    } catch (error) {
      const message =
        error instanceof HttpError ? error.message : "断开失败，请稍后重试。";
      toast({ title: "断开失败", description: message, variant: "destructive" });
    } finally {
      setPendingId(null);
      setDisconnectTarget(null);
    }
  }

  const isEmpty = useMemo(() => !loading && connectors.length === 0, [loading, connectors]);

  return (
    <>
      <div className="flex h-full w-full flex-col overflow-y-auto bg-[#faf9f7]">
        <div className="flex items-center px-6 pt-[calc(0.9rem+env(safe-area-inset-top))]">
          <PageBackButton ariaLabel="back-connectors" onClick={handleBack} />
        </div>

        <header className="px-6 pb-4 pt-2">
          <h1 className="text-xl font-semibold text-ink">应用授权</h1>
          <p className="mt-1 text-sm leading-6 text-[#5f696a]">
            连接你的常用应用后，我可以代你查询、追踪进度。所有授权随时可以断开。
          </p>
        </header>

        <section className="flex-1 px-4 pb-10">
          {loading ? (
            <div className="flex items-center justify-center py-16 text-sm text-[#809b9f]">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              读取应用列表…
            </div>
          ) : null}

          {isEmpty ? (
            <div className="rounded-2xl bg-white p-8 text-center text-sm text-[#809b9f] shadow-sm">
              暂未配置可授权的应用。
            </div>
          ) : null}

          <div className="space-y-3">
            {connectors.map((connector) => {
              const badge = STATUS_BADGES[connector.status] ?? STATUS_BADGES.disconnected;
              const connected = isConnected(connector.status);
              const inFlight = pendingId === connector.id;
              return (
                <article
                  key={connector.id}
                  className="rounded-2xl bg-white p-4 shadow-sm"
                >
                  <div className="flex items-start gap-3">
                    {connector.icon_url ? (
                      <img
                        src={connector.icon_url}
                        alt={`${connector.display_name} 图标`}
                        className="mt-0.5 h-10 w-10 rounded-lg object-contain"
                        loading="lazy"
                      />
                    ) : (
                      <div className="mt-0.5 flex h-10 w-10 items-center justify-center rounded-lg bg-[#f4ebd9] text-[#d4704e]">
                        <Plug className="h-5 w-5" />
                      </div>
                    )}

                    <div className="min-w-0 flex-1">
                      <div className="flex items-center justify-between gap-2">
                        <h2 className="truncate text-base font-medium text-ink">
                          {connector.display_name}
                        </h2>
                        <span
                          className={`inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-xs ${badge.className}`}
                        >
                          {badge.icon}
                          {badge.label}
                        </span>
                      </div>
                      {connector.description ? (
                        <p className="mt-1.5 text-sm leading-6 text-[#5f696a]">
                          {connector.description}
                        </p>
                      ) : null}
                      {connector.last_error && !connected ? (
                        <p className="mt-1.5 text-xs leading-5 text-rose-600">
                          {connector.last_error}
                        </p>
                      ) : null}
                    </div>
                  </div>

                  <div className="mt-3 flex items-center justify-end gap-2">
                    {connected ? (
                      <>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-8 px-3 text-rose-600 hover:bg-rose-50 hover:text-rose-700"
                          disabled={inFlight}
                          onClick={() => setDisconnectTarget(connector)}
                        >
                          <Trash2 className="mr-1 h-3.5 w-3.5" />
                          断开
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          className="h-8 px-3"
                          disabled={inFlight}
                          onClick={() => handleConnect(connector)}
                        >
                          {inFlight ? (
                            <>
                              <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
                              重新授权…
                            </>
                          ) : (
                            "重新授权"
                          )}
                        </Button>
                      </>
                    ) : (
                      <Button
                        size="sm"
                        className="h-8 px-3"
                        disabled={inFlight}
                        onClick={() => handleConnect(connector)}
                      >
                        {inFlight ? (
                          <>
                            <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
                            打开授权页…
                          </>
                        ) : (
                          "连接"
                        )}
                      </Button>
                    )}
                  </div>
                </article>
              );
            })}
          </div>
        </section>
      </div>

      <ConfirmDialog
        open={disconnectTarget !== null}
        onOpenChange={(open) => {
          if (!open) {
            setDisconnectTarget(null);
          }
        }}
        title="断开授权"
        description={
          disconnectTarget
            ? `撤销与 ${disconnectTarget.display_name} 的连接后，助手将无法访问该应用的数据。`
            : ""
        }
        cancelLabel="取消"
        confirmLabel="确认断开"
        onCancel={() => setDisconnectTarget(null)}
        onConfirm={() => {
          if (disconnectTarget) {
            void handleDisconnect(disconnectTarget);
          }
        }}
      />
    </>
  );
}
