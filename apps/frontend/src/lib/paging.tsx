/**
 * Lists that load a page at a time: the first page is live (onSnapshot, so new items appear
 * at once), older pages are fetched when the end of the list scrolls into view. Pages use the
 * query's own order and startAfter, so no extra Firestore index is needed, and only what you
 * scroll to is read (free Firestore: 50k reads a day).
 */
import { useCallback, useEffect, useRef, useState, type RefObject } from "react";
import {
  getDocs, limit, onSnapshot, query, startAfter, type DocumentData, type Query, type QueryDocumentSnapshot,
} from "firebase/firestore";

type Snap = QueryDocumentSnapshot<DocumentData>;

export function usePaged<T>(base: Query<DocumentData> | null, key: string, pageSize = 20) {
  const [first, setFirst] = useState<Snap[]>([]);
  const [older, setOlder] = useState<Snap[]>([]);
  const [more, setMore] = useState(false);
  const [loading, setLoading] = useState(false);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<{ code?: string } | null>(null);
  const generation = useRef(0);

  useEffect(() => {
    generation.current += 1;
    setFirst([]);
    setOlder([]);
    setMore(false);
    setReady(false);
    setError(null);
    if (!base) return;
    return onSnapshot(
      query(base, limit(pageSize)),
      (s) => {
        setFirst(s.docs);
        setMore((m) => m || s.docs.length === pageSize);
        setReady(true);
      },
      (e) => setError(e),
    );
    // the key stands for the query (Query objects aren't stable between renders)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, pageSize]);

  const loadMore = useCallback(async () => {
    const last = older[older.length - 1] ?? first[first.length - 1];
    if (!base || !last || loading || !more) return;
    const gen = generation.current;
    setLoading(true);
    try {
      const s = await getDocs(query(base, startAfter(last), limit(pageSize)));
      if (gen !== generation.current) return;
      setOlder((o) => [...o, ...s.docs]);
      setMore(s.docs.length === pageSize);
    } catch (e) {
      setError(e as { code?: string });
    } finally {
      if (gen === generation.current) setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, first, older, loading, more, pageSize]);

  // a new item at the top pushes one off the live page into "older": show each once
  const seen = new Set<string>();
  const rows = [...first, ...older]
    .filter((d) => (seen.has(d.id) ? false : (seen.add(d.id), true)))
    .map((d) => ({ id: d.id, ...(d.data() as T) }));
  return { rows, more, loading, ready, error, loadMore };
}

/** Calls onVisible when it scrolls into view inside `root` (the scrolling container). */
export function LoadMore({ root, more, loading, onVisible, done }: {
  root: RefObject<HTMLElement | null>;
  more: boolean;
  loading: boolean;
  onVisible: () => void;
  done?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el || !more) return;
    const io = new IntersectionObserver((e) => e[0].isIntersecting && onVisible(), { root: root.current, rootMargin: "150px" });
    io.observe(el);
    return () => io.disconnect();
  }, [root, more, onVisible]);
  return (
    <div ref={ref} className="list-end muted small" aria-live="polite">
      {loading ? <><span className="spinner" /> Loading more…</> : !more && done ? done : ""}
    </div>
  );
}
