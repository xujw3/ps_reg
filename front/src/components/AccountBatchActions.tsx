import { ChevronDown, ListChecks, Loader2, Trash2 } from "lucide-react";
import { Button } from "@/components/ui";

export function AccountBatchActions({
  selectedCount,
  busy,
  menuOpen,
  onToggleMenu,
  onCloseMenu,
  onDelete,
}: {
  selectedCount: number;
  busy: boolean;
  menuOpen: boolean;
  onToggleMenu: () => void;
  onCloseMenu: () => void;
  onDelete: () => void;
}) {
  return (
    <div className="relative">
      <Button
        variant="outline"
        className="w-full"
        onClick={onToggleMenu}
        disabled={!selectedCount || busy}
        aria-haspopup="menu"
        aria-expanded={menuOpen}
      >
        {busy ? (
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
        ) : (
          <ListChecks className="h-4 w-4" aria-hidden="true" />
        )}
        批量操作 ({selectedCount})
        <ChevronDown className="h-4 w-4" aria-hidden="true" />
      </Button>
      {menuOpen ? (
        <>
          <button
            type="button"
            className="fixed inset-0 z-30 cursor-default"
            onClick={onCloseMenu}
            aria-label="关闭批量操作"
          />
          <div
            role="menu"
            className="absolute right-0 top-[calc(100%+0.5rem)] z-40 w-64 rounded-lg border bg-card p-2 shadow-2xl"
          >
            <button
              type="button"
              role="menuitem"
              className="flex min-h-10 w-full items-center gap-2 rounded-lg px-3 text-left text-sm font-medium text-destructive hover:bg-red-50"
              onClick={onDelete}
            >
              <Trash2 className="h-4 w-4" aria-hidden="true" />
              删除选中账号
            </button>
          </div>
        </>
      ) : null}
    </div>
  );
}
