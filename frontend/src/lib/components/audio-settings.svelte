<script lang="ts">
  import { api } from '$lib/api';
  import { longpress } from '$lib/actions/longpress';
  import Label from '$lib/components/ui/label.svelte';
  import CountBadge from '$lib/components/ui/count-badge.svelte';
  import DeleteHint from '$lib/components/delete-hint.svelte';
  import { askConfirm } from '$lib/confirm.svelte';
  import Field from '$lib/components/ui/field.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import Input from '$lib/components/ui/input.svelte';
  import { inputStr } from '$lib/dom-helpers';
  import { CircleCheck } from 'lucide-svelte';

  interface AudioRow {
    name: string;
    keywords: string[];
  }

  let rows = $state<AudioRow[]>([]);
  let search = $state('');
  let error = $state<string | null>(null);
  let savedMsg = $state<string | null>(null);

  let modal = $state<{ mode: 'new' } | { mode: 'edit'; name: string } | null>(null);
  let ctxMenu = $state<{ x: number; y: number; name: string } | null>(null);
  let draftName = $state('');
  let draftKeywords = $state('');

  async function load() {
    error = null;
    try {
      const resp = await api.get<{ sections: Record<string, object> }>('/api/config');
      const t = (resp.sections || {}).audio_taxonomy as { classes?: string[]; keywords?: Record<string, string[]> } | undefined;
      const classes = t?.classes ?? [];
      const keywords = t?.keywords ?? {};
      rows = classes.map((name) => ({ name, keywords: keywords[name] ?? [] }));
    } catch (e) {
      error = `Failed to load audio settings: ${(e as Error).message}`;
    }
  }

  $effect(() => { load(); });

  const filtered = $derived(rows.filter((r) => r.name.toLowerCase().includes(search.toLowerCase())));

  function keywordsToText(kw: string[]): string {
    return kw.join(', ');
  }
  function parseKeywords(text: string): string[] {
    return text.split(',').map((s) => s.trim()).filter(Boolean);
  }

  function openNew() {
    draftName = '';
    draftKeywords = '';
    modal = { mode: 'new' };
  }

  function openEdit(name: string) {
    const row = rows.find((r) => r.name === name);
    draftName = name;
    draftKeywords = keywordsToText(row?.keywords ?? []);
    modal = { mode: 'edit', name };
  }

  async function persist(list: AudioRow[]) {
    const classes = list.map((r) => r.name);
    const keywords: Record<string, string[]> = {};
    for (const r of list) keywords[r.name] = r.keywords;
    await api.putJson('/api/config/audio_taxonomy', { classes, keywords });
  }

  async function save() {
    error = null;
    if (!draftName.trim()) { error = 'Class name is required.'; return; }
    const name = draftName.trim();
    let next: AudioRow[];
    if (modal?.mode === 'new') {
      next = [...rows, { name, keywords: parseKeywords(draftKeywords) }];
    } else {
      const old = modal!.name;
      next = rows.map((r) => (r.name === old ? { name, keywords: parseKeywords(draftKeywords) } : r));
    }
    try {
      await persist(next);
      rows = next;
      modal = null;
      savedMsg = `Saved audio class '${name}'.`;
      setTimeout(() => (savedMsg = null), 3000);
    } catch (e) {
      error = `Failed to save: ${(e as Error).message}`;
    }
  }

  async function remove(name: string) {
    if (!(await askConfirm(`Delete audio class '${name}'?`, { title: 'Delete audio class' }))) return;
    const next = rows.filter((r) => r.name !== name);
    try {
      await persist(next);
      rows = next;
      if (modal?.mode === 'edit' && modal.name === name) modal = null;
    } catch (e) {
      error = `Failed to delete: ${(e as Error).message}`;
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
    <span class="text-sm font-semibold">Audio</span>
    <CountBadge filtered={filtered.length} total={rows.length} filtering={search.trim() !== ''} />
    <Input class="h-7 flex-1 font-mono text-xs" placeholder="Search audio classes…" value={search} oninput={(e) => (search = (e.currentTarget as HTMLInputElement).value)} />
    <button type="button" class="rounded border px-1.5 py-0.5 text-xs text-muted-foreground hover:bg-muted" title="Add class" onclick={openNew}>＋</button>
  </div>
  <DeleteHint />

  <div class="min-h-0 flex-1 space-y-1 overflow-y-auto pr-1">
    {#each filtered as r (r.name)}
      <div
        role="button"
        tabindex="0"
        class="group flex cursor-pointer select-none touch-callout-none items-center gap-2 rounded-md border px-2 py-1.5 transition-colors hover:border-primary/50 hover:bg-muted/40"
        onclick={() => openEdit(r.name)}
        onkeydown={(ev) => { if (ev.key === 'Enter') openEdit(r.name); }}
        oncontextmenu={(e) => { e.preventDefault(); ctxMenu = { x: e.clientX, y: e.clientY, name: r.name }; }}
        use:longpress={{ onLongPress: (e) => { ctxMenu = { x: e.clientX, y: e.clientY, name: r.name }; } }}
        title="Click to configure synonyms"
      >
        <span class="w-28 shrink-0 truncate font-mono text-sm font-medium sm:w-48" title={r.name}>{r.name}</span>
        <span class="min-w-0 flex-1 truncate text-xs text-muted-foreground" title={r.keywords.join(', ')}>{r.keywords.length ? r.keywords.join(', ') : 'no synonyms'}</span>
      </div>
    {:else}
      <p class="pt-2 text-sm text-muted-foreground">
        {rows.length === 0 ? 'No audio classes defined.' : 'No classes match your search.'}
      </p>
    {/each}
  </div>
</div>

{#if modal}
  <div class="fixed inset-0 z-50 flex items-center justify-center p-4" role="presentation" onkeydown={(e) => { if (e.key === 'Escape') modal = null; }}>
    <div class="absolute inset-0 bg-black/40" onclick={() => (modal = null)} role="presentation"></div>
    <div class="relative z-10 w-full max-w-sm rounded-2xl border bg-card p-5 shadow-float" role="dialog" aria-modal="true" tabindex="-1">
      <div class="mb-3 text-sm font-semibold">{modal.mode === 'new' ? 'New Audio Class' : 'Edit Audio Class'}</div>
      <div class="space-y-3">
        <Field>
          <Label>Name</Label>
          <Input class="w-full font-mono" placeholder="class_name" value={draftName} onchange={(e) => (draftName = inputStr(e))} />
        </Field>
        <Field>
          <Label>Synonyms</Label>
          <textarea class={textareaClass} rows={3} placeholder="optional i.e. class_name1, class_name2" value={draftKeywords}
            onchange={(e) => (draftKeywords = (e.currentTarget as HTMLTextAreaElement).value)}></textarea>
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
    <button type="button" class="block w-full px-3 py-1 text-left hover:bg-muted" onclick={() => { remove(ctxMenu!.name); ctxMenu = null; }}>Delete</button>
  </div>
{/if}
