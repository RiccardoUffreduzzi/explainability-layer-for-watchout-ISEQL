<script lang="ts">
  import { onMount } from 'svelte';
  import { untrack } from 'svelte';
  import { longpress } from '$lib/actions/longpress';
  import Input from '$lib/components/ui/input.svelte';
  import CountBadge from '$lib/components/ui/count-badge.svelte';
  import DeleteHint from '$lib/components/delete-hint.svelte';
  import { askConfirm } from '$lib/confirm.svelte';
  import IseqlIntervalModal from '$lib/components/iseql-interval-modal.svelte';
  import IseqlOperatorModal from '$lib/components/iseql-operator-modal.svelte';
  import IseqlExprTree from '$lib/components/iseql-expr-tree.svelte';
  import IseqlGroupModal from '$lib/components/iseql-group-modal.svelte';
  import {
    detectOperator,
    emptyOperator,
    emptyState,
    flattenIntervals,
    intervalLabel,
    isLeaf,
    leaf,
    modelToState,
    nextId,
    stateToModel,
    type BuilderGroup,
    type BuilderInterval,
    type BuilderOperator,
    type ExprNode,
    type IseqlModel,
    type Modality,
    type Unit,
    type Vocabulary,
  } from '$lib/iseql-model';
  import type { Condition } from '$lib/types';
  import { inputStr } from '$lib/dom-helpers';
  import { timelineUi } from '$lib/iseql-ui-state.svelte';

  type Props = {
    condition: Condition;
    model: IseqlModel | null;
    vocabulary: Vocabulary;
    eventName: string;
    unit: Unit;
    onChange: (model: IseqlModel) => void;
    onOpenPredicate?: (name: string, modality: 'visual' | 'audio') => void;
  };
  let { condition, model, vocabulary, eventName, unit, onChange, onOpenPredicate = () => undefined }: Props = $props();

  // -------------------------------------------------------------------------
  // state
  // -------------------------------------------------------------------------
  let groups = $state<BuilderGroup[]>([]);
  let expr = $state<ExprNode | null>(null);
  let scale = $state(timelineUi.scale);
  let activeGroup = $state<string>('');

  let modal = $state<{ gi: number; pi: number } | null>(null);
  let intervalModal = $state<{ gi: number; ii: number } | null>(null);
  let groupModal = $state<{ mode: 'new' } | { mode: 'edit'; name: string } | null>(null);
  let hoverGroups = $state<string[]>([]);

  let canvas = $state<HTMLCanvasElement | null>(null);
  let scroller = $state<HTMLDivElement | null>(null);

  // transient, non-reactive
  let drag: { gi: number; ii: number; mode: 'move' | 'resize_l' | 'resize_r'; x0: number; ts0: number; te0: number } | null = null;
  let drawDrag: { x0: number; y0: number; x1: number; y1: number } | null = null;
  let ctxMenu = $state<{ x: number; y: number; gi: number; ii: number } | null>(null);
  let setCtxMenu = $state<{ x: number; y: number; name: string } | null>(null);
  let downPos: { x: number; y: number } | null = null;

  // touch pan/zoom (two fingers) bookkeeping
  const pointers = new Map<number, { x: number; y: number }>();
  let panning = false;
  let panStart: { sl: number; st: number; cx: number; cy: number } | null = null;
  let pinchStart: { scale: number; dist: number } | null = null;

  const predModality = $derived.by(() => {
    const m = new Map<string, Modality>();
    for (const p of vocabulary.predicates) m.set(p.name, p.modality);
    return m;
  });

  // -------------------------------------------------------------------------
  // hydration + emit
  // -------------------------------------------------------------------------

  function hydrate(m: IseqlModel | null) {
    const st = m ? modelToState(m) : emptyState();
    const prevActive = untrack(() => activeGroup);
    groups = st.groups;
    expr = st.expr;
    activeGroup = st.groups.some((g) => g.name === prevActive) ? prevActive : (st.groups[0]?.name ?? '');
    modal = null;
    intervalModal = null;
    groupModal = null;
  }

  // Guard against re-hydrating from the model we just emitted ourselves: Svelte
  // wraps `$state` objects in a proxy, so reference equality between the
  // emitted model and the parent's `model` prop does not hold.
  let suppressHydrate = false;

  $effect(() => {
    if (suppressHydrate) {
      suppressHydrate = false;
      return;
    }
    hydrate(model);
  });

  $effect(() => {
    timelineUi.scale = scale;
  });

  // Re-emit when the parent changes the unit so the projection domain and
  // delta_unit stay in sync (the parent owns the Time/Frames switcher).
  let lastUnit: Unit = untrack(() => unit);
  $effect(() => {
    if (unit !== lastUnit) {
      lastUnit = unit;
      swapProjectionTemporal(unit);
      emit();
    }
  });

  // Swap st/et <-> sf/ef in each group's explicit projection so the temporal
  // domain follows the Time/Frames unit (argument fields are unchanged).
  function swapProjectionTemporal(to: Unit) {
    const map: Record<string, string> = to === 'frames' ? { st: 'sf', et: 'ef' } : { sf: 'st', ef: 'et' };
    groups = groups.map((g) => {
      if (!g.projection) return g;
      return {
        ...g,
        projection: g.projection.map((f) => f.replace(/\.(st|et|sf|ef)$/, (_m, a: string) => `.${map[a] ?? a}`)),
      };
    });
  }

  function emit() {
    const m = stateToModel({ groups, expr, unit }, eventName || 'event');
    suppressHydrate = true;
    onChange(m);
  }

  function changed() {
    emit();
  }

  // -------------------------------------------------------------------------
  // layout helpers
  // -------------------------------------------------------------------------

  const PAD = 56;
  const ROW_H = 64;
  const RECT_H = 30;
  const ROW_Y = 18;
  const HANDLE_W = 6;
  const LANE_H = 26;
  const TOP = 8;

  interface Row { gi: number; ii: number; y: number; globalIndex: number; }
  interface Header { gi: number; name: string; y: number; }
  interface Badge { gi: number; pi: number; x: number; y: number; }

  const flat = $derived(flattenIntervals(groups));

  const minTs = $derived(flat.length ? Math.min(...flat.map((f) => f.interval.ts)) : 0);
  const maxTe = $derived(flat.length ? Math.max(...flat.map((f) => f.interval.te)) : 0);
  const maxT = $derived(Math.max(maxTe - minTs + 40, unit === 'seconds' ? 60 : 200));

  function tsPx(t: number) { return PAD + Math.round((t - minTs) * scale); }
  function pxTs(x: number) { return minTs + Math.max(0, Math.round((x - PAD) / scale)); }

  function computeLayout(): { rows: Row[]; headers: Header[]; badges: Badge[]; totalH: number } {
    const rows: Row[] = [];
    const headers: Header[] = [];
    const badges: Badge[] = [];
    let y = TOP;
    let g = 0;
    groups.forEach((grp, gi) => {
      headers.push({ gi, name: grp.name, y });
      y += LANE_H;
      grp.intervals.forEach((_, ii) => {
        rows.push({ gi, ii, y, globalIndex: g++ });
        y += ROW_H;
      });
      // operator badges between consecutive intervals in this group
      for (let pi = 0; pi < grp.ops.length; pi++) {
        const ra = rows.find((r) => r.gi === gi && r.ii === pi);
        const rb = rows.find((r) => r.gi === gi && r.ii === pi + 1);
        if (ra && rb) {
          const a = grp.intervals[pi];
          const b = grp.intervals[pi + 1];
          const xA = (tsPx(a.ts) + tsPx(a.te)) / 2;
          const xB = (tsPx(b.ts) + tsPx(b.te)) / 2;
          badges.push({ gi, pi, x: (xA + xB) / 2, y: (ra.y + ROW_H + rb.y) / 2 });
        }
      }
    });
    return { rows, headers, badges, totalH: y + 40 };
  }

  function ivColor(globalIndex: number, modality: Modality | undefined): string {
    if (modality === 'audio') return '#f9c74f';
    const COLORS = ['#7c6af7', '#56cfb2', '#f38ba8', '#fab387', '#a6e3a1', '#89dceb', '#cba6f7'];
    return COLORS[globalIndex % COLORS.length];
  }

  function intervalBounds(row: Row) {
    const iv = groups[row.gi].intervals[row.ii];
    return { x1: tsPx(iv.ts), x2: tsPx(iv.te), y1: row.y + ROW_Y, h: RECT_H };
  }

  // -------------------------------------------------------------------------
  // drawing
  // -------------------------------------------------------------------------

  function draw() {
    const c = canvas;
    if (!c) return;
    const layout = computeLayout();
    const totalW = tsPx(minTs + maxT) + PAD + 60;
    const totalH = layout.totalH + 60;
    if (c.width !== totalW) c.width = totalW;
    if (c.height !== totalH) c.height = totalH;
    const ctx = c.getContext('2d');
    if (!ctx) return;

    const bg = cssColor('--background', '#0b0b10');
    const gridMinor = cssColor('--border', '#2a2a3e');
    const textDim = cssColor('--muted-foreground', '#888');
    const textFg = cssColor('--foreground', '#eee');

    ctx.clearRect(0, 0, totalW, totalH);
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, totalW, totalH);

    // grid (adaptive so labels/gridlines don't overlap at small zoom)
    const NICE = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000, 100000];
    function niceStep(minPx: number): number {
      for (const s of NICE) {
        if (s * scale >= minPx) return s;
      }
      return NICE[NICE.length - 1];
    }
    const labelStep = niceStep(60);
    const minorStep = niceStep(12);
    for (let t = 0; t <= maxT; t += minorStep) {
      const abs = minTs + t;
      const x = tsPx(abs);
      const isLabel = t % labelStep === 0;
      ctx.strokeStyle = gridMinor;
      ctx.lineWidth = isLabel ? 1 : 0.5;
      ctx.setLineDash(isLabel ? [3, 4] : [1, 5]);
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, totalH); ctx.stroke();
      if (isLabel) {
        ctx.setLineDash([]);
        ctx.fillStyle = textDim;
        ctx.font = '10px sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText(String(abs), x, totalH - 8);
      }
    }
    ctx.setLineDash([]);

    // group headers (lane separators)
    for (const h of layout.headers) {
      const isActive = h.name === activeGroup;
      const rowCount = groups[h.gi].intervals.length;
      // header band
      ctx.fillStyle = isActive ? cssColor('--accent', '#2a2a3e') : gridMinor;
      ctx.globalAlpha = 0.35;
      ctx.fillRect(0, h.y, totalW, LANE_H - 4);
      ctx.globalAlpha = 1;
      // separator line
      ctx.strokeStyle = gridMinor;
      ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(0, h.y + LANE_H - 4); ctx.lineTo(totalW, h.y + LANE_H - 4); ctx.stroke();
      // label
      ctx.fillStyle = isActive ? textFg : textDim;
      ctx.font = 'bold 10px sans-serif';
      ctx.textAlign = 'left';
      if (h.name) ctx.fillText(`Set ${h.name}`, PAD, h.y + 12);
      if (rowCount === 0) {
        ctx.fillStyle = textDim;
        ctx.font = '9px sans-serif';
        ctx.textAlign = 'right';
        ctx.fillText('(empty)', totalW - 12, h.y + 12);
      }
    }

    // intervals
    for (const row of layout.rows) {
      const iv = groups[row.gi].intervals[row.ii];
      const color = ivColor(row.globalIndex, predModality.get(iv.pred));
      const { x1, x2, y1 } = intervalBounds(row);
      const highlighted = hoverGroups.includes(groups[row.gi].name);

      if (row.ii > 0) {
        ctx.strokeStyle = gridMinor;
        ctx.lineWidth = 0.5;
        ctx.setLineDash([1, 6]);
        ctx.beginPath(); ctx.moveTo(0, row.y - 2); ctx.lineTo(totalW, row.y - 2); ctx.stroke();
        ctx.setLineDash([]);
      }

      ctx.fillStyle = textDim;
      ctx.font = 'bold 9px sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText(`M${row.globalIndex + 1}`, PAD / 2, row.y + ROW_H / 2 + 3);

      // shadow
      ctx.fillStyle = 'rgba(0,0,0,.18)';
      ctx.fillRect(x1 + 2, y1 + 2, x2 - x1, RECT_H);

      ctx.fillStyle = color;
      roundRect(ctx, x1, y1, x2 - x1, RECT_H, 4);
      ctx.fill();

      if (highlighted) {
        ctx.strokeStyle = color;
        ctx.lineWidth = 2;
        roundRect(ctx, x1 - 2, y1 - 2, x2 - x1 + 4, RECT_H + 4, 6);
        ctx.stroke();
      }

      const ivW = x2 - x1;
      if (ivW > 24) {
        const label = intervalLabel(iv);
        ctx.fillStyle = 'rgba(0,0,0,.65)';
        ctx.font = 'bold 10px sans-serif';
        ctx.textAlign = 'center';
        ctx.save();
        ctx.beginPath();
        ctx.rect(x1 + 4, y1, ivW - 8, RECT_H);
        ctx.clip();
        ctx.fillText(label, (x1 + x2) / 2, y1 + RECT_H / 2 + 4);
        ctx.restore();
      }

      ctx.fillStyle = color;
      ctx.font = '9px monospace';
      ctx.textAlign = 'left';
      ctx.fillText(String(iv.ts), x1 + 1, y1 - 5);
      ctx.textAlign = 'right';
      ctx.fillText(String(iv.te), x2 - 1, y1 - 5);

      for (const hx of [x1, x2]) {
        ctx.fillStyle = bg;
        ctx.strokeStyle = color;
        ctx.lineWidth = 1.5;
        ctx.fillRect(hx - HANDLE_W, y1, HANDLE_W * 2, RECT_H);
        ctx.strokeRect(hx - HANDLE_W, y1, HANDLE_W * 2, RECT_H);
      }
    }

    // operator badges
    for (const b of layout.badges) {
      const op = groups[b.gi].ops[b.pi];
      const label = op.op && op.op !== 'auto' ? op.op : detectOperator(groups[b.gi].intervals[b.pi], groups[b.gi].intervals[b.pi + 1]).op;
      ctx.beginPath();
      ctx.arc(b.x, b.y, 12, 0, Math.PI * 2);
      ctx.fillStyle = '#f59e0b';
      ctx.fill();
      ctx.strokeStyle = 'rgba(0,0,0,.5)';
      ctx.lineWidth = 1;
      ctx.stroke();
      ctx.fillStyle = '#111111';
      ctx.font = 'bold 9px sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(label, b.x, b.y + 0.5);
      ctx.textBaseline = 'alphabetic';
    }

    // ghost
    if (drawDrag) {
      const gx1 = Math.min(drawDrag.x0, drawDrag.x1);
      const gx2 = Math.max(drawDrag.x0, drawDrag.x1);
      const gy = Math.min(drawDrag.y0, drawDrag.y1);
      ctx.save();
      ctx.strokeStyle = '#a6e3a1';
      ctx.lineWidth = 2;
      ctx.setLineDash([6, 4]);
      ctx.globalAlpha = 0.7;
      roundRect(ctx, gx1, gy - RECT_H / 2, gx2 - gx1, RECT_H, 4);
      ctx.stroke();
      ctx.restore();
    }
  }

  function cssColor(name: string, fallback: string): string {
    const raw = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return raw ? `hsl(${raw})` : fallback;
  }

  function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.lineTo(x + w - r, y);
    ctx.quadraticCurveTo(x + w, y, x + w, y + r);
    ctx.lineTo(x + w, y + h - r);
    ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
    ctx.lineTo(x + r, y + h);
    ctx.quadraticCurveTo(x, y + h, x, y + h - r);
    ctx.lineTo(x, y + r);
    ctx.quadraticCurveTo(x, y, x + r, y);
    ctx.closePath();
  }

  $effect(() => {
    void groups;
    void scale;
    void unit;
    void activeGroup;
    void hoverGroups;
    void expr;
    draw();
  });

  onMount(() => {
    if (canvas) canvas.addEventListener('wheel', onWheel, { passive: false });
    return () => {
      canvas?.removeEventListener('wheel', onWheel);
    };
  });

  function onWheel(e: WheelEvent) {
    e.preventDefault();
    const step = Math.max(1, Math.round(scale / 6));
    scale = Math.max(2, Math.min(48, scale + (e.deltaY < 0 ? step : -step)));
  }

  // -------------------------------------------------------------------------
  // hit testing + pointer interaction
  // -------------------------------------------------------------------------

  function canvasXY(e: { clientX: number; clientY: number }) {
    const r = canvas!.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
  }

  function hitTest(x: number, y: number): { gi: number; ii: number; mode: 'move' | 'resize_l' | 'resize_r' } | { gi: number; pi: number; mode: 'badge' } | { gi: number; mode: 'header' } | null {
    const layout = computeLayout();
    for (const b of layout.badges) {
      if (Math.hypot(x - b.x, y - b.y) <= 13) return { gi: b.gi, pi: b.pi, mode: 'badge' };
    }
    for (const h of layout.headers) {
      if (y >= h.y && y <= h.y + LANE_H) return { gi: h.gi, mode: 'header' };
    }
    for (let r = layout.rows.length - 1; r >= 0; r--) {
      const row = layout.rows[r];
      const { x1, x2, y1, h } = intervalBounds(row);
      if (y < y1 || y > y1 + h) continue;
      if (Math.abs(x - x1) <= HANDLE_W + 2) return { gi: row.gi, ii: row.ii, mode: 'resize_l' };
      if (Math.abs(x - x2) <= HANDLE_W + 2) return { gi: row.gi, ii: row.ii, mode: 'resize_r' };
      if (x >= x1 && x <= x2) return { gi: row.gi, ii: row.ii, mode: 'move' };
    }
    return null;
  }

  function groupAtY(y: number): number {
    const layout = computeLayout();
    for (let i = groups.length - 1; i >= 0; i--) {
      const h = layout.headers[i];
      if (y >= h.y) return i;
    }
    return groups.length - 1;
  }

  function onPointerDown(e: PointerEvent) {
    if (e.button !== 0) return;
    ctxMenu = null;
    const { x, y } = canvasXY(e);
    pointers.set(e.pointerId, { x, y });

    // A second simultaneous touch enters pan/pinch mode (touch only).
    if (pointers.size >= 2) {
      drag = null;
      drawDrag = null;
      panning = true;
      const pts = [...pointers.values()];
      const cx = (pts[0].x + pts[1].x) / 2;
      const cy = (pts[0].y + pts[1].y) / 2;
      panStart = {
        sl: scroller?.scrollLeft ?? 0,
        st: scroller?.scrollTop ?? 0,
        cx,
        cy,
      };
      pinchStart = { scale, dist: Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y) };
      return;
    }

    if (panning) return;

    downPos = { x, y };
    const hit = hitTest(x, y);
    if (hit && hit.mode === 'badge') {
      modal = { gi: hit.gi, pi: hit.pi };
      return;
    }
    if (hit && hit.mode === 'header') {
      activeGroup = groups[hit.gi].name;
      return;
    }
    if (hit && (hit.mode === 'move' || hit.mode === 'resize_l' || hit.mode === 'resize_r')) {
      const iv = groups[hit.gi].intervals[hit.ii];
      drag = { gi: hit.gi, ii: hit.ii, mode: hit.mode, x0: x, ts0: iv.ts, te0: iv.te };
      canvas?.setPointerCapture(e.pointerId);
      return;
    }
    drawDrag = { x0: x, y0: y, x1: x, y1: y };
    canvas?.setPointerCapture(e.pointerId);
  }

  function onPointerMove(e: PointerEvent) {
    const { x, y } = canvasXY(e);
    pointers.set(e.pointerId, { x, y });

    if (panning && pointers.size >= 2) {
      const pts = [...pointers.values()];
      const cx = (pts[0].x + pts[1].x) / 2;
      const cy = (pts[0].y + pts[1].y) / 2;
      if (panStart && pinchStart && scroller) {
        scroller.scrollLeft = panStart.sl - (cx - panStart.cx);
        scroller.scrollTop = panStart.st - (cy - panStart.cy);
        const dist = Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y);
        if (pinchStart.dist > 0) {
          const next = Math.max(2, Math.min(48, pinchStart.scale * (dist / pinchStart.dist)));
          scale = next;
        }
      }
      return;
    }

    if (downPos && (Math.abs(x - downPos.x) + Math.abs(y - downPos.y)) > 4) downPos = null;

    if (drawDrag) {
      drawDrag.x1 = x;
      drawDrag.y1 = y;
      draw();
      return;
    }
    if (!drag) return;
    const dt = (x - drag.x0) / scale;
    const iv = groups[drag.gi].intervals[drag.ii];
    if (drag.mode === 'move') {
      const ts = Math.max(0, Math.round(drag.ts0 + dt));
      iv.ts = ts;
      iv.te = ts + (drag.te0 - drag.ts0);
    } else if (drag.mode === 'resize_l') {
      iv.ts = Math.max(0, Math.min(Math.round(drag.ts0 + dt), drag.te0 - 1));
      iv.te = drag.te0;
    } else {
      iv.te = Math.max(drag.ts0 + 1, Math.round(drag.te0 + dt));
      iv.ts = drag.ts0;
    }
  }

  function onPointerUp(e: PointerEvent) {
    pointers.delete(e.pointerId);

    if (panning && pointers.size < 2) {
      panning = false;
      panStart = null;
      pinchStart = null;
      if (pointers.size === 1) {
        // Remaining finger should not suddenly start drawing/moving.
        downPos = null;
        drag = null;
        drawDrag = null;
      }
      return;
    }

    if (drawDrag) {
      const rawTs = pxTs(Math.min(drawDrag.x0, drawDrag.x1));
      const rawTe = pxTs(Math.max(drawDrag.x0, drawDrag.x1));
      const gy = (drawDrag.y0 + drawDrag.y1) / 2;
      const gi = groupAtY(gy);
      drawDrag = null;
      draw();
      if (rawTe - rawTs >= 1) {
        addDrawnInterval(gi, rawTs, rawTe);
      }
      return;
    }
    if (!drag) return;
    drag = null;
    emit();
  }

  function onClick(e: MouseEvent) {
    if (!downPos) return;
    const { x, y } = canvasXY(e);
    const hit = hitTest(x, y);
    if (hit && hit.mode === 'move') {
      intervalModal = { gi: hit.gi, ii: hit.ii };
    }
  }

  function onContextMenu(e: MouseEvent) {
    e.preventDefault();
    const { x, y } = canvasXY(e);
    const hit = hitTest(x, y);
    if (hit && (hit.mode === 'move' || hit.mode === 'resize_l' || hit.mode === 'resize_r')) {
      ctxMenu = { x: e.clientX, y: e.clientY, gi: hit.gi, ii: hit.ii };
    }
  }

  // -------------------------------------------------------------------------
  // mutations
  // -------------------------------------------------------------------------

  function addDrawnInterval(gi: number, ts: number, te: number) {
    addInterval(gi, ts, te);
  }

  function addInterval(gi: number, ts?: number, te?: number) {
    if (gi < 0 || gi >= groups.length) return;
    const g = groups[gi];
    const last = g.intervals[g.intervals.length - 1];
    const start = ts ?? (last ? last.te : 0);
    const end = te ?? start + 100;
    const iv: BuilderInterval = { id: nextId(), pred: '', args: [], ts: start, te: end };
    g.intervals = [...g.intervals, iv];
    g.ops = [...g.ops, emptyOperator()];
    intervalModal = { gi, ii: g.intervals.length - 1 };
  }

  function nextGroupName(): string {
    let i = 1;
    while (groups.some((g) => g.name === `s${i}`)) i++;
    return `s${i}`;
  }

  function newGroup() {
    groupModal = { mode: 'new' };
  }

  function openGroupModal(name: string) {
    activeGroup = name;
    groupModal = { mode: 'edit', name };
  }

  function saveGroup(edited: BuilderGroup) {
    if (!groupModal) return;
    if (groupModal.mode === 'new') {
      groups = [...groups, edited];
      activeGroup = edited.name;
      if (!expr) expr = leaf(edited.name);
    } else {
      const old = groupModal.name;
      groups = groups.map((g) => (g.name === old ? edited : g));
      if (edited.name !== old) {
        expr = expr ? renameInExpr(expr, old, edited.name) : null;
        if (activeGroup === old) activeGroup = edited.name;
      }
    }
    groupModal = null;
    changed();
  }

  function deleteSetByName(name: string) {
    const gi = groups.findIndex((g) => g.name === name);
    if (gi < 0) return;
    const set = groups[gi];
    const unassignedIdx = groups.findIndex((g) => g.name === '');
    const unassigned = groups[unassignedIdx];
    // preserve the set's intervals by moving them to the unassigned lane
    if (unassigned) {
      unassigned.intervals = [...unassigned.intervals, ...set.intervals];
      unassigned.ops = [...unassigned.ops, ...set.ops];
    }
    groups = groups.filter((_, i) => i !== gi);
    expr = removeGroupFromExpr(expr, name);
    if (activeGroup === name) activeGroup = '';
    changed();
  }

  function removeGroupFromExpr(node: ExprNode | null, name: string): ExprNode | null {
    if (!node) return null;
    if (isLeaf(node)) return node.group === name ? null : node;
    const children = node.children
      .map((c) => removeGroupFromExpr(c, name))
      .filter((c): c is ExprNode => c != null);
    if (children.length === 0) return null;
    if (children.length === 1) return children[0];
    return { ...node, children };
  }

  function renameInExpr(node: ExprNode, old: string, name: string): ExprNode {
    if (isLeaf(node)) return node.group === old ? { ...node, group: name } : node;
    return { ...node, children: node.children.map((c) => renameInExpr(c, old, name)) };
  }

  function saveInterval(gi: number, ii: number, d: { pred: string; args: string[]; ts: number; te: number; group: string; selection?: Record<string, unknown> | null }) {
    const g = groups[gi];
    let targetGi = gi;
    if (d.group !== g.name) {
      const tgi = groups.findIndex((x) => x.name === d.group);
      if (tgi >= 0) targetGi = tgi;
    }
    const iv: BuilderInterval = { ...g.intervals[ii], pred: d.pred, args: d.args, ts: d.ts, te: d.te };
    if (d.selection) iv.selection = d.selection;
    else delete iv.selection;
    if (targetGi === gi) {
      g.intervals = g.intervals.map((x, k) => (k === ii ? iv : x));
    } else {
      g.intervals = g.intervals.filter((_, k) => k !== ii);
      g.ops = g.ops.slice(0, g.intervals.length - 1);
      const tg = groups[targetGi];
      tg.intervals = [...tg.intervals, iv];
      tg.ops = [...tg.ops, emptyOperator()];
    }
    intervalModal = null;
    changed();
  }

  function removeInterval(gi: number, ii: number) {
    const g = groups[gi];
    g.intervals = g.intervals.filter((_, k) => k !== ii);
    g.ops = g.ops.slice(0, g.intervals.length - 1);
    intervalModal = null;
    changed();
  }

  function closeIntervalModal() {
    if (intervalModal) {
      const { gi, ii } = intervalModal;
      const iv = groups[gi]?.intervals[ii];
      if (iv && !iv.pred.trim()) {
        removeInterval(gi, ii);
        return;
      }
    }
    intervalModal = null;
  }

  function saveOp(op: BuilderOperator) {
    if (!modal) return;
    const { gi, pi } = modal;
    const g = groups[gi];
    g.ops = g.ops.map((o, k) => (k === pi ? op : o));
    modal = null;
    changed();
  }

  function setScale(v: number) {
    scale = v;
  }

  // -------------------------------------------------------------------------
  // derived helpers
  // -------------------------------------------------------------------------

  const activeGroupIdx = $derived(groups.findIndex((g) => g.name === activeGroup));
  const setNames = $derived(groups.filter((g) => g.name !== '').map((g) => g.name));

  let intervalSearch = $state('');
  let setSearch = $state('');

  const filteredFlat = $derived(
    flat.filter((f) => intervalLabel(f.interval).toLowerCase().includes(intervalSearch.trim().toLowerCase())),
  );
  const filteredSetNames = $derived(
    setNames.filter((n) => n.toLowerCase().includes(setSearch.trim().toLowerCase())),
  );

  const modalA = $derived(modal ? groups[modal.gi].intervals[modal.pi] : null);
  const modalB = $derived(modal ? groups[modal.gi].intervals[modal.pi + 1] : null);
  const modalOp = $derived(modal ? groups[modal.gi].ops[modal.pi] : emptyOperator());
  const groupModalIsNew = $derived(groupModal?.mode === 'new');
  const groupModalObj = $derived.by((): BuilderGroup | null => {
    if (!groupModal) return null;
    if (groupModal.mode === 'edit') {
      const name = groupModal.name;
      return groups.find((g) => g.name === name) ?? null;
    }
    return { name: nextGroupName(), intervals: [], ops: [], projection: null, crossConditions: [] };
  });
  const intervalDraft = $derived(intervalModal ? (() => {
    const iv = groups[intervalModal.gi].intervals[intervalModal.ii];
    return { pred: iv.pred, args: iv.args, ts: iv.ts, te: iv.te, group: groups[intervalModal.gi].name, selection: iv.selection ?? null };
  })() : null);
</script>

<div class="flex min-h-0 flex-1 flex-col gap-2">
  <!-- toolbar -->
  <div class="flex shrink-0 flex-wrap items-center gap-2 rounded-lg border px-2 py-1 text-xs">
    <span class="text-muted-foreground">Zoom</span>
    <input type="range" min="2" max="48" value={scale} oninput={(e) => setScale(Number((e.currentTarget as HTMLInputElement).value))} class="w-32" />
    <span class="font-mono text-muted-foreground">{scale}px</span>
  </div>

  <p class="shrink-0 text-xs text-muted-foreground">
    Drag on empty canvas to draw an interval · scroll or pinch to zoom · two-finger drag to pan · drag a block to move · drag its edges to resize · click an interval to edit · click a relation badge to set the operator.
  </p>

  <!-- main area -->
  <div class="flex min-h-0 flex-1 flex-col gap-2 overflow-hidden lg:flex-row">
    <div bind:this={scroller} class="min-h-0 flex-1 overflow-auto rounded-lg border" data-tour="editor-canvas">
      <canvas
        bind:this={canvas}
        class="block touch-none select-none"
        onpointerdown={onPointerDown}
        onpointermove={onPointerMove}
        onpointerup={onPointerUp}
        onpointercancel={onPointerUp}
        onclick={onClick}
        oncontextmenu={onContextMenu}
        use:longpress={{ onLongPress: (e) => {
          const { x, y } = canvasXY(e);
          const hit = hitTest(x, y);
          if (hit && hit.mode === 'move') {
            drag = null;
            downPos = null;
            ctxMenu = { x: e.clientX, y: e.clientY, gi: hit.gi, ii: hit.ii };
            draw();
          }
        } }}
      ></canvas>
    </div>

    <div class="flex w-full shrink-0 flex-col gap-2 overflow-y-auto rounded-lg border p-2 lg:w-80" data-tour="editor-intervals">
      <!-- Intervals card -->
      <div class="rounded-lg border p-2">
        <div class="mb-1 flex items-center gap-1">
          <span class="shrink-0 text-xs font-semibold">Intervals</span>
          <CountBadge filtered={filteredFlat.length} total={flat.length} filtering={intervalSearch.trim() !== ''} />
          <Input class="h-6 min-w-0 flex-1 font-mono text-xs" placeholder="Search intervals…" value={intervalSearch} oninput={(e) => (intervalSearch = (e.currentTarget as HTMLInputElement).value)} />
          <button type="button" class="shrink-0 rounded-md border px-1.5 py-0.5 text-xs text-muted-foreground hover:bg-muted" title="Add interval" disabled={activeGroupIdx < 0} onclick={() => addInterval(activeGroupIdx)}>＋</button>
        </div>
        <DeleteHint />
        <div class="max-h-40 space-y-1 overflow-y-auto pr-1">
          {#each filteredFlat as f (f.globalIndex)}
            <button
              type="button"
              class="w-full select-none touch-callout-none rounded-md border px-2 py-1 text-left font-mono text-xs hover:bg-muted"
              onclick={() => (intervalModal = { gi: groups.findIndex((g) => g.name === f.group), ii: f.localIndex })}
              oncontextmenu={(e) => { e.preventDefault(); ctxMenu = { x: e.clientX, y: e.clientY, gi: groups.findIndex((g) => g.name === f.group), ii: f.localIndex }; }}
              use:longpress={{ onLongPress: (e) => { ctxMenu = { x: e.clientX, y: e.clientY, gi: groups.findIndex((g) => g.name === f.group), ii: f.localIndex }; } }}
            >
              <span class="text-muted-foreground">M{f.globalIndex + 1}</span> {f.interval.pred ? intervalLabel(f.interval) : 'Empty'}
            </button>
          {:else}
            <p class="text-xs text-muted-foreground">No intervals.</p>
          {/each}
        </div>
      </div>

      <!-- Sets list card -->
      <div class="rounded-lg border p-2">
        <div class="mb-1 flex items-center gap-1">
          <span class="shrink-0 text-xs font-semibold">Sets</span>
          <CountBadge filtered={filteredSetNames.length} total={setNames.length} filtering={setSearch.trim() !== ''} />
          <Input class="h-6 min-w-0 flex-1 font-mono text-xs" placeholder="Search sets…" value={setSearch} oninput={(e) => (setSearch = (e.currentTarget as HTMLInputElement).value)} />
          <button type="button" class="shrink-0 rounded-md border px-1.5 py-0.5 text-xs text-muted-foreground hover:bg-muted" title="Add set" onclick={newGroup}>＋</button>
        </div>
        <DeleteHint />
        <div class="max-h-40 space-y-1 overflow-y-auto pr-1">
          {#each filteredSetNames as name (name)}
            <button
              type="button"
              class="w-full select-none touch-callout-none rounded-md border px-2 py-1 text-left font-mono text-xs hover:bg-muted"
              onclick={() => openGroupModal(name)}
              oncontextmenu={(e) => { e.preventDefault(); setCtxMenu = { x: e.clientX, y: e.clientY, name }; }}
              use:longpress={{ onLongPress: (e) => { setCtxMenu = { x: e.clientX, y: e.clientY, name }; } }}
            >{name}</button>
          {:else}
            <p class="text-xs text-muted-foreground">No sets.</p>
          {/each}
        </div>
      </div>

      <!-- Set expression card -->
      <div class="rounded-lg border p-2">
        <div class="mb-1 text-xs font-semibold">Set Expression</div>
        <IseqlExprTree
          {expr}
          groupNames={setNames}
          onExpr={(e) => { expr = e; changed(); }}
          onOpenGroup={openGroupModal}
          onHover={(g) => (hoverGroups = g)}
        />
      </div>
    </div>
  </div>

  <!-- interval config modal -->
  <IseqlIntervalModal
    open={intervalModal != null}
    {condition}
    {vocabulary}
    groupOptions={setNames}
    initial={intervalDraft}
    onSave={(d) => { if (intervalModal) saveInterval(intervalModal.gi, intervalModal.ii, d); }}
    onClose={closeIntervalModal}
    {onOpenPredicate}
  />

  <!-- operator modal -->
  <IseqlOperatorModal
    open={modal != null}
    a={modalA ?? { id: 'x', pred: '', args: [], ts: 0, te: 0 }}
    b={modalB ?? { id: 'y', pred: '', args: [], ts: 0, te: 0 }}
    initial={modalOp}
    onSave={saveOp}
    onClose={() => (modal = null)}
  />

  <!-- group config modal -->
  <IseqlGroupModal
    open={groupModal != null}
    group={groupModalObj}
    isNew={groupModalIsNew}
    {unit}
    onSave={saveGroup}
    onClose={() => (groupModal = null)}
  />

  <!-- context menu -->
  {#if ctxMenu}
    <div class="fixed inset-0 z-50" role="presentation" onclick={() => (ctxMenu = null)} oncontextmenu={(e) => { e.preventDefault(); ctxMenu = null; }}></div>
    <div class="fixed z-50 w-44 rounded-xl border bg-popover py-1 text-xs shadow-float" style="left: {ctxMenu.x}px; top: {ctxMenu.y}px">
      <button type="button" class="block w-full px-3 py-1 text-left hover:bg-muted" onclick={async () => { if (await askConfirm('Delete this interval?', { title: 'Delete interval' })) removeInterval(ctxMenu!.gi, ctxMenu!.ii); ctxMenu = null; }}>Delete</button>
    </div>
  {/if}

  {#if setCtxMenu}
    <div class="fixed inset-0 z-50" role="presentation" onclick={() => (setCtxMenu = null)} oncontextmenu={(e) => { e.preventDefault(); setCtxMenu = null; }}></div>
    <div class="fixed z-50 w-44 rounded-xl border bg-popover py-1 text-xs shadow-float" style="left: {setCtxMenu.x}px; top: {setCtxMenu.y}px">
      <button type="button" class="block w-full px-3 py-1 text-left hover:bg-muted" onclick={async () => { if (await askConfirm(`Delete set '${setCtxMenu!.name}'? Its intervals move to the unassigned lane.`, { title: 'Delete set' })) deleteSetByName(setCtxMenu!.name); setCtxMenu = null; }}>Delete</button>
    </div>
  {/if}
</div>
