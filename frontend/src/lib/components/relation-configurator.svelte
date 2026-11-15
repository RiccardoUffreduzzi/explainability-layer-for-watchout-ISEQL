<script lang="ts">
  import { api } from '$lib/api';
  import { longpress } from '$lib/actions/longpress';
  import Input from '$lib/components/ui/input.svelte';
  import CountBadge from '$lib/components/ui/count-badge.svelte';
  import DeleteHint from '$lib/components/delete-hint.svelte';
  import { askConfirm } from '$lib/confirm.svelte';
  import Label from '$lib/components/ui/label.svelte';
  import Field from '$lib/components/ui/field.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import { inputStr } from '$lib/dom-helpers';
  import { CircleCheck } from 'lucide-svelte';

  interface RelationRow {
    name: string;
    args: string;
    description: string;
  }

  type Props = {
    focusRelation?: string | null;
    onFocused?: () => void;
  };
  let { focusRelation = null, onFocused = () => undefined }: Props = $props();

  let rows = $state<RelationRow[]>([]);
  let search = $state('');
  let error = $state<string | null>(null);
  let savedMsg = $state<string | null>(null);

  let modal = $state<{ mode: 'new' } | { mode: 'edit'; index: number } | null>(null);
  let ctxMenu = $state<{ x: number; y: number; index: number } | null>(null);
  let draft = $state<RelationRow>({ name: '', args: '', description: '' });
  let argsTa = $state<HTMLTextAreaElement | null>(null);

  const argsWarn = $derived((() => {
    const a = draft.args;
    if (!a) return null;
    if (a.includes('|')) return 'Use ∨ (logical OR) instead of | between alternatives.';
    if (a.includes('V')) return 'Use ∨ (logical OR) instead of V between alternatives.';
    if (/(^|\s)v(\s|$)/.test(a)) return 'Use ∨ (logical OR) instead of v between alternatives.';
    return null;
  })());

  function insertOr() {
    const ta = argsTa;
    if (!ta) {
      draft = { ...draft, args: `${draft.args} ∨ `.trimStart() };
      return;
    }
    const start = ta.selectionStart ?? draft.args.length;
    const end = ta.selectionEnd ?? start;
    const next = draft.args.slice(0, start) + ' ∨ ' + draft.args.slice(end);
    draft = { ...draft, args: next };
    requestAnimationFrame(() => {
      ta.focus();
      const caret = start + 3;
      ta.setSelectionRange(caret, caret);
    });
  }

  async function load() {
    error = null;
    try {
      const resp = await api.get<{ relations: RelationRow[] }>('/api/relations');
      rows = resp.relations ?? [];
    } catch (e) {
      error = `Failed to load relations: ${(e as Error).message}`;
    }
  }

  $effect(() => {
    load();
  });

  // When navigating here from a predicate click, open the matching relation.
  let focused = false;
  $effect(() => {
    if (focused || !focusRelation) return;
    const idx = rows.findIndex((r) => r.name === focusRelation);
    if (idx >= 0) {
      focused = true;
      openEdit(idx);
      onFocused();
    }
  });

  const filtered = $derived(
    rows.filter((r) => r.name.toLowerCase().includes(search.toLowerCase()))
  );

  function openEdit(index: number) {
    draft = { ...rows[index] };
    modal = { mode: 'edit', index };
    error = null;
    savedMsg = null;
  }

  function openNew() {
    draft = { name: '', args: '', description: '' };
    modal = { mode: 'new' };
    error = null;
    savedMsg = null;
  }

  function toPayload(list: RelationRow[]) {
    const valid = list.filter((r) => r.name.trim());
    return { relations: valid.map((r) => ({ name: r.name.trim(), args: r.args.trim(), description: r.description.trim() })) };
  }

  async function save() {
    error = null;
    if (!draft.name.trim()) { error = 'Relation name is required.'; return; }
    const isNew = modal?.mode === 'new';
    const editIndex = modal?.mode === 'edit' ? modal.index : -1;
    const next = isNew
      ? [...rows, { ...draft, name: draft.name.trim() }]
      : rows.map((r, i) => (i === editIndex ? { ...draft, name: draft.name.trim() } : r));
    try {
      await api.putJson('/api/relations', toPayload(next));
      rows = next;
      modal = null;
      savedMsg = `Saved relation '${draft.name.trim()}'.`;
      setTimeout(() => (savedMsg = null), 3000);
    } catch (e) {
      error = `Failed to save relation: ${(e as Error).message}`;
    }
  }

  async function remove(index: number) {
    const name = rows[index]?.name ?? `#${index + 1}`;
    if (!(await askConfirm(`Delete visual relation '${name}'?`, { title: 'Delete relation' }))) return;
    const next = rows.filter((_, idx) => idx !== index);
    try {
      await api.putJson('/api/relations', toPayload(next));
      rows = next;
      if (modal?.mode === 'edit' && modal.index === index) modal = null;
    } catch (err) {
      error = `Failed to delete relation: ${(err as Error).message}`;
    }
  }

  const textareaClass =
    'w-full resize-y rounded-lg border border-input bg-card px-3 py-2 font-mono text-xs leading-relaxed ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2';
</script>

<div class="flex min-h-0 flex-1 flex-col gap-2 overflow-hidden pt-1">
  {#if error}<p class="text-sm text-destructive">{error}</p>{/if}
  {#if savedMsg}
    <div class="flex shrink-0 items-start gap-2.5 rounded-lg border border-success/40 bg-success/10 px-3 py-2.5" role="status">
      <CircleCheck class="mt-0.5 size-4 shrink-0 text-success" />
      <p class="min-w-0 flex-1 break-words text-xs leading-relaxed text-success">{savedMsg}</p>
    </div>
  {/if}

  <div class="flex shrink-0 items-center gap-2">
    <span class="text-sm font-semibold">Visual</span>
    <CountBadge filtered={filtered.length} total={rows.length} filtering={search.trim() !== ''} />
    <Input class="h-7 flex-1 font-mono text-xs" placeholder="Search predicates…" value={search} oninput={(e) => (search = (e.currentTarget as HTMLInputElement).value)} />
    <button type="button" class="rounded border px-1.5 py-0.5 text-xs text-muted-foreground hover:bg-muted" title="Add relation" onclick={openNew}>＋</button>
  </div>
  <DeleteHint />

  <div class="min-h-0 flex-1 space-y-1 overflow-y-auto pr-1">
    {#each filtered as r, i (r.name)}
      <div
        role="button"
        tabindex="0"
        class="group flex cursor-pointer select-none touch-callout-none items-center gap-2 rounded-md border px-2 py-1.5 transition-colors hover:border-primary/50 hover:bg-muted/40"
        onclick={() => openEdit(rows.indexOf(r))}
        onkeydown={(ev) => { if (ev.key === 'Enter') openEdit(rows.indexOf(r)); }}
        oncontextmenu={(e) => { e.preventDefault(); ctxMenu = { x: e.clientX, y: e.clientY, index: rows.indexOf(r) }; }}
        use:longpress={{ onLongPress: (e) => { ctxMenu = { x: e.clientX, y: e.clientY, index: rows.indexOf(r) }; } }}
        title="Click to edit"
      >
        <span class="w-28 shrink-0 truncate font-mono text-sm font-medium sm:w-48" title={r.name}>{r.name || '(unnamed)'}</span>
        <span class="w-28 shrink-0 truncate font-mono text-xs text-muted-foreground sm:w-40" title={r.args}>{r.args || '-'}</span>
        <span class="min-w-0 flex-1 truncate text-xs text-muted-foreground" title={r.description}>{r.description || '-'}</span>
      </div>
    {:else}
      <p class="pt-2 text-sm text-muted-foreground">
        {rows.length === 0 ? 'No relations defined.' : 'No relations match your search.'}
      </p>
    {/each}
  </div>
</div>

{#if modal}
  <div class="fixed inset-0 z-50 flex items-center justify-center p-4" role="presentation" onkeydown={(e) => { if (e.key === 'Escape') modal = null; }}>
    <div class="absolute inset-0 bg-black/40" onclick={() => (modal = null)} role="presentation"></div>
    <div class="relative z-10 w-full max-w-md rounded-2xl border bg-card p-5 shadow-float" role="dialog" aria-modal="true" tabindex="-1">
      <div class="mb-3 text-sm font-semibold">{modal.mode === 'new' ? 'New Visual Relation' : 'Edit Visual Relation'}</div>
      <div class="space-y-3">
        <Field>
          <Label>Name</Label>
          <Input class="w-full font-mono" placeholder="relation_name" value={draft.name} onchange={(e) => (draft = { ...draft, name: inputStr(e) })} />
        </Field>
        <Field>
          <Label>Args</Label>
          <textarea bind:this={argsTa} class={textareaClass} rows={2} placeholder="arg1, arg2 ∨ arg3" value={draft.args}
            onchange={(e) => (draft = { ...draft, args: (e.currentTarget as HTMLTextAreaElement).value })}></textarea>
          <div class="flex items-center gap-2">
            <button
              type="button"
              class="rounded border border-input px-1.5 py-0.5 font-mono text-xs text-muted-foreground hover:bg-accent hover:text-foreground"
              title="Insert OR (∨)"
              onclick={insertOr}
            >∨</button>
            <p class="text-xs text-muted-foreground">
              Separate arguments with a comma; use <span class="font-mono">∨</span> for OR within an argument, e.g. <span class="font-mono">person, vehicle ∨ object</span>.
            </p>
          </div>
          {#if argsWarn}
            <p class="text-xs text-warning">{argsWarn}</p>
          {/if}
        </Field>
        <Field>
          <Label>Description</Label>
          <textarea class={textareaClass} rows={5} placeholder="Describe the relation (used in the prompt)" value={draft.description}
            onchange={(e) => (draft = { ...draft, description: (e.currentTarget as HTMLTextAreaElement).value })}></textarea>
        </Field>
      </div>
      <div class="mt-4 flex justify-end gap-2">
        <Button type="button" variant="ghost" onclick={() => (modal = null)}>Cancel</Button>
        <Button type="button" onclick={save}>Save</Button>
      </div>
    </div>
  </div>
{/if}

{#if ctxMenu}
  <div class="fixed inset-0 z-50" role="presentation" onclick={() => (ctxMenu = null)} oncontextmenu={(e) => { e.preventDefault(); ctxMenu = null; }}></div>
  <div class="fixed z-50 w-44 rounded-xl border bg-popover py-1 text-xs shadow-float" style="left: {ctxMenu.x}px; top: {ctxMenu.y}px">
    <button type="button" class="block w-full px-3 py-1 text-left hover:bg-muted" onclick={() => { remove(ctxMenu!.index); ctxMenu = null; }}>Delete</button>
  </div>
{/if}
