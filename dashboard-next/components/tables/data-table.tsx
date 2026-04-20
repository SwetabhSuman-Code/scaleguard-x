import type { ReactNode } from "react";

import { EmptyState } from "@/components/ui/state-blocks";
import { cn } from "@/lib/format";

export interface DataColumn<T> {
  header: string;
  render: (row: T) => ReactNode;
  className?: string;
}

export function DataTable<T>({
  rows,
  columns,
  getKey,
  emptyTitle,
}: {
  rows: T[];
  columns: Array<DataColumn<T>>;
  getKey: (row: T, index: number) => string | number;
  emptyTitle?: string;
}) {
  if (rows.length === 0) {
    return <EmptyState title={emptyTitle} />;
  }

  return (
    <div className="overflow-hidden rounded-[1.6rem] border border-ink/10 bg-panel/70">
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-ink/10 text-left text-sm">
          <thead className="bg-ink text-paper">
            <tr>
              {columns.map((column) => (
                <th
                  key={column.header}
                  className={cn(
                    "whitespace-nowrap px-4 py-3 text-xs font-extrabold uppercase tracking-[0.18em] text-paper/75",
                    column.className,
                  )}
                >
                  {column.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-ink/[0.08]">
            {rows.map((row, index) => (
              <tr key={getKey(row, index)} className="transition hover:bg-white/[0.65]">
                {columns.map((column) => (
                  <td
                    key={column.header}
                    className={cn("whitespace-nowrap px-4 py-3 font-semibold text-graphite", column.className)}
                  >
                    {column.render(row)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
