"use client";

import { useEffect, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ChevronRight, Trash2 } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { ApiError, apiFetch } from "@/lib/api";
import { masteryStatuses, type BulkResult, type MasteryStatus, type Question } from "@/types/api";

interface QuestionTableProps {
  items: Question[];
}

function chipClassName(status: string) {
  if (status === "已掌握" || status === "已完成") return "bg-[#E8F8F3] text-[#079976]";
  if (status === "复习中" || status === "分析中") return "bg-[#FFF4DE] text-[#C97A00]";
  if (status === "未掌握" || status === "失败") return "bg-[#FFF0F1] text-[#D84755]";
  return "bg-[#F1F3F9] text-[#52627F]";
}

function dateLabel(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return "—";
  return new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit" }).format(date);
}

function errorMessage(error: unknown) {
  return error instanceof ApiError ? error.body.message : "操作失败，请检查网络后重试";
}

interface DeleteDialogProps {
  count: number;
  onCancel: () => void;
  onConfirm: () => void;
  isPending: boolean;
  returnFocus: HTMLElement | null;
  error: string | null;
}

function DeleteDialog({ count, onCancel, onConfirm, isPending, returnFocus, error }: DeleteDialogProps) {
  const cancelButton = useRef<HTMLButtonElement>(null);
  const dialog = useRef<HTMLElement>(null);

  useEffect(() => {
    cancelButton.current?.focus();
    return () => returnFocus?.focus();
  }, [returnFocus]);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && !isPending) onCancel();
      if (event.key !== "Tab") return;

      const focusable = Array.from(
        dialog.current?.querySelectorAll<HTMLElement>("button:not([disabled]), select:not([disabled]), [href], [tabindex]:not([tabindex='-1'])") ?? [],
      );
      const first = focusable[0];
      const last = focusable.at(-1);
      if (!first || !last) return;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [isPending, onCancel]);

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-[#0D1B4C]/35 p-4">
      <section ref={dialog} role="dialog" aria-modal="true" aria-labelledby="bulk-delete-title" className="w-full max-w-md rounded-xl border border-[#E4E8F2] bg-white p-6 shadow-xl">
        <h2 id="bulk-delete-title" className="text-lg font-semibold text-[#0D1B4C]">确认删除错题</h2>
        <p className="mt-3 text-sm leading-6 text-[#52627F]">将永久删除已选择的 {count} 道错题及其分析和复习记录，此操作无法撤销。</p>
        {error ? <p className="mt-4 rounded-lg border border-[#FFD7DB] bg-[#FFF7F8] px-3 py-2 text-sm text-[#C33746]" role="alert">{error}</p> : null}
        <div className="mt-6 flex justify-end gap-3">
          <Button ref={cancelButton} variant="secondary" onClick={onCancel} disabled={isPending}>取消</Button>
          <Button className="border-[#D84755] bg-[#D84755] hover:bg-[#BE3442]" onClick={onConfirm} disabled={isPending}>
            {isPending ? "正在删除…" : "确认删除"}
          </Button>
        </div>
      </section>
    </div>
  );
}

export function QuestionTable({ items }: QuestionTableProps) {
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<string[]>([]);
  const [pendingDelete, setPendingDelete] = useState<string[] | null>(null);
  const [deleteReturnFocus, setDeleteReturnFocus] = useState<HTMLElement | null>(null);
  const [bulkStatus, setBulkStatus] = useState<MasteryStatus>("复习中");
  const [actionError, setActionError] = useState<string | null>(null);
  const visibleIds = new Set(items.map((item) => item.id));
  const visibleSelected = selected.filter((id) => visibleIds.has(id));
  const allSelected = items.length > 0 && visibleSelected.length === items.length;

  function refreshQuestions() {
    queryClient.invalidateQueries({ queryKey: ["questions"] });
  }

  const updateStatus = useMutation({
    mutationFn: () => apiFetch<BulkResult>("/questions/bulk-status", { method: "POST", body: JSON.stringify({ ids: visibleSelected, mastery_status: bulkStatus }) }),
    onMutate: () => setActionError(null),
    onSuccess: () => {
      setSelected([]);
      refreshQuestions();
    },
    onError: (error) => setActionError(errorMessage(error)),
  });

  const deleteQuestions = useMutation({
    mutationFn: (ids: string[]) => apiFetch<BulkResult>("/questions/bulk-delete", { method: "POST", body: JSON.stringify({ ids }) }),
    onMutate: () => setActionError(null),
    onSuccess: () => {
      setSelected([]);
      setPendingDelete(null);
      refreshQuestions();
    },
    onError: (error) => setActionError(errorMessage(error)),
  });

  function toggleAll() {
    setSelected(allSelected ? [] : items.map((item) => item.id));
  }

  function toggleOne(id: string) {
    setSelected((current) => current.includes(id) ? current.filter((value) => value !== id) : [...current, id]);
  }

  function requestDeletion(ids: string[]) {
    setActionError(null);
    setDeleteReturnFocus(document.activeElement instanceof HTMLElement ? document.activeElement : null);
    setPendingDelete(ids);
  }

  return (
    <section className="overflow-hidden rounded-xl border border-[#E4E8F2] bg-white" aria-labelledby="question-table-title">
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-[#E8ECF4] px-5 py-4 sm:px-6">
        <div>
          <h2 id="question-table-title" className="text-base font-semibold text-[#0D1B4C]">错题列表</h2>
          <p className="mt-1 text-sm text-[#6A7893]">已选择 {visibleSelected.length} 道错题</p>
        </div>
        {visibleSelected.length ? (
          <div className="flex flex-wrap items-center gap-2">
            <label className="sr-only" htmlFor="bulk-mastery-status">批量掌握状态</label>
            <select id="bulk-mastery-status" aria-label="批量掌握状态" className="h-9 rounded-lg border border-[#E4E8F2] bg-white px-2 text-sm text-[#314568]" value={bulkStatus} onChange={(event) => setBulkStatus(event.target.value as MasteryStatus)}>
              {masteryStatuses.map((status) => <option key={status} value={status}>{status}</option>)}
            </select>
            <Button variant="secondary" size="sm" onClick={() => updateStatus.mutate()} disabled={updateStatus.isPending}>批量修改状态</Button>
            <Button className="border-[#D84755] bg-[#D84755] hover:bg-[#BE3442]" size="sm" onClick={() => requestDeletion(visibleSelected)}>批量删除</Button>
          </div>
        ) : null}
      </div>
      {actionError && !pendingDelete ? <p className="mx-5 mt-4 text-sm text-[#D84755]" role="alert">{actionError}</p> : null}
      {items.length === 0 ? (
        <div className="px-6 py-14 text-center">
          <p className="text-base font-medium text-[#0D1B4C]">暂无符合条件的错题</p>
          <p className="mt-2 text-sm text-[#6A7893]">调整筛选条件，或先录入一道错题开始复盘。</p>
        </div>
      ) : (
        <>
          <ul className="divide-y divide-[#E8ECF4] md:hidden" aria-label="移动端错题列表">
            {items.map((item) => (
              <li key={item.id} className="space-y-4 px-4 py-5">
                <div className="flex items-start gap-3">
                  <input
                    type="checkbox"
                    aria-label={`选择卡片错题 ${item.stem}`}
                    checked={selected.includes(item.id)}
                    onChange={() => toggleOne(item.id)}
                    className="mt-1 size-4 shrink-0 accent-[#4F46E5]"
                  />
                  <div className="min-w-0 flex-1">
                    <Link href={`/questions/${item.id}`} className="line-clamp-3 font-medium leading-6 text-[#0D1B4C] hover:text-[#4F46E5] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#4F46E5]">{item.stem}</Link>
                    <p className="mt-1 text-xs text-[#6A7893]">{item.module} · {dateLabel(item.created_at)}</p>
                  </div>
                </div>
                <dl className="grid grid-cols-2 gap-3 text-sm">
                  <div><dt className="text-xs text-[#6A7893]">知识点</dt><dd className="mt-1 text-[#314568]">{item.knowledge_points.length ? item.knowledge_points.join("、") : "—"}</dd></div>
                  <div><dt className="text-xs text-[#6A7893]">错因</dt><dd className="mt-1 text-[#314568]">{item.error_reason ?? "—"}</dd></div>
                  <div><dt className="text-xs text-[#6A7893]">掌握状态</dt><dd className="mt-1"><span className={`inline-flex rounded-md px-2 py-1 text-xs font-medium ${chipClassName(item.mastery_status)}`}>{item.mastery_status}</span></dd></div>
                  <div><dt className="text-xs text-[#6A7893]">AI 状态</dt><dd className="mt-1"><span className={`inline-flex rounded-md px-2 py-1 text-xs font-medium ${chipClassName(item.analysis_status)}`}>{item.analysis_status}</span></dd></div>
                </dl>
                <div className="flex items-center justify-end gap-1 border-t border-[#E8ECF4] pt-3">
                  <Link href={`/questions/${item.id}`} className="inline-flex h-9 items-center gap-1 rounded-lg px-3 text-sm font-medium text-[#4F46E5] hover:bg-[#EEF0FF] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#4F46E5]">查看详情<ChevronRight className="size-4" aria-hidden="true" /></Link>
                  <Button variant="ghost" size="icon" aria-label={`删除卡片错题 ${item.stem}`} onClick={() => requestDeletion([item.id])}><Trash2 className="size-4 text-[#D84755]" aria-hidden="true" /></Button>
                </div>
              </li>
            ))}
          </ul>
          <div className="hidden overflow-x-auto md:block">
          <table className="w-full min-w-[980px] text-left text-sm">
            <thead className="border-b border-[#E8ECF4] bg-[#FBFCFE] text-xs font-medium text-[#6A7893]">
              <tr>
                <th className="w-12 px-5 py-3"><input type="checkbox" aria-label="选择全部错题" checked={allSelected} onChange={toggleAll} /></th>
                <th className="px-3 py-3">题目摘要</th>
                <th className="px-3 py-3">模块</th>
                <th className="px-3 py-3">知识点</th>
                <th className="px-3 py-3">错因</th>
                <th className="px-3 py-3">掌握状态</th>
                <th className="px-3 py-3">AI 状态</th>
                <th className="px-3 py-3">创建时间</th>
                <th className="px-3 py-3">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#E8ECF4] text-[#314568]">
              {items.map((item) => (
                <tr key={item.id} className="hover:bg-[#FBFCFE]">
                  <td className="px-5 py-4"><input type="checkbox" aria-label={`选择错题 ${item.stem}`} checked={selected.includes(item.id)} onChange={() => toggleOne(item.id)} /></td>
                  <td className="max-w-72 px-3 py-4"><Link href={`/questions/${item.id}`} className="line-clamp-2 font-medium text-[#0D1B4C] hover:text-[#4F46E5] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#4F46E5]">{item.stem}</Link></td>
                  <td className="px-3 py-4 whitespace-nowrap">{item.module}</td>
                  <td className="max-w-36 px-3 py-4"><span className="line-clamp-2">{item.knowledge_points.length ? item.knowledge_points.join("、") : "—"}</span></td>
                  <td className="px-3 py-4">{item.error_reason ?? "—"}</td>
                  <td className="px-3 py-4"><span className={`inline-flex rounded-md px-2 py-1 text-xs font-medium ${chipClassName(item.mastery_status)}`}>{item.mastery_status}</span></td>
                  <td className="px-3 py-4"><span className={`inline-flex rounded-md px-2 py-1 text-xs font-medium ${chipClassName(item.analysis_status)}`}>{item.analysis_status}</span></td>
                  <td className="px-3 py-4 whitespace-nowrap">{dateLabel(item.created_at)}</td>
                  <td className="px-3 py-4"><div className="flex items-center gap-1"><Link href={`/questions/${item.id}`} className="inline-flex h-9 items-center gap-1 rounded-lg px-2 text-sm font-medium text-[#4F46E5] hover:bg-[#EEF0FF]">查看<ChevronRight className="size-4" aria-hidden="true" /></Link><Button variant="ghost" size="icon" aria-label={`删除错题 ${item.stem}`} onClick={() => requestDeletion([item.id])}><Trash2 className="size-4 text-[#D84755]" aria-hidden="true" /></Button></div></td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        </>
      )}
      {pendingDelete ? <DeleteDialog count={pendingDelete.length} onCancel={() => setPendingDelete(null)} onConfirm={() => deleteQuestions.mutate(pendingDelete)} isPending={deleteQuestions.isPending} returnFocus={deleteReturnFocus} error={actionError} /> : null}
    </section>
  );
}
