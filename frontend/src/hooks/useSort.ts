import { useEffect, useMemo, useState } from "react";

export type SortDirection = "asc" | "desc";

export interface SortState<T extends string> {
  field: T;
  direction: SortDirection;
}

/** Generic client-side sorting for tables and lists. */
export function useSort<T extends string>(initialField: T, initialDirection: SortDirection = "asc") {
  const [sort, setSort] = useState<SortState<T>>({
    field: initialField,
    direction: initialDirection,
  });

  function toggle(field: T) {
    setSort((current) =>
      current.field === field
        ? { field, direction: current.direction === "asc" ? "desc" : "asc" }
        : { field, direction: "asc" },
    );
  }

  return { sort, toggle, setSort };
}

type Comparator<T> = (a: T, b: T) => number;

export function sortItems<T>(
  items: T[],
  sort: SortState<string>,
  comparators: Record<string, Comparator<T>>,
): T[] {
  const comparator = comparators[sort.field];
  if (!comparator) return items;
  const sorted = [...items].sort(comparator);
  return sort.direction === "asc" ? sorted : sorted.reverse();
}

/** Client-side pagination with a page that stays inside the valid range. */
export function usePagination(total: number, pageSize = 10) {
  const [page, setPage] = useState(1);
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const safePage = Math.min(page, pageCount);

  const slice = useMemo(() => {
    const start = (safePage - 1) * pageSize;
    return { start, end: start + pageSize };
  }, [safePage, pageSize]);

  return { page: safePage, pageSize, pageCount, setPage, ...slice };
}

export function useDebounced<T>(value: T, delay = 220): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const handle = window.setTimeout(() => setDebounced(value), delay);
    return () => window.clearTimeout(handle);
  }, [value, delay]);
  return debounced;
}
