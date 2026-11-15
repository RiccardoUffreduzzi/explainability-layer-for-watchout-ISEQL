<script lang="ts">
  import Button from '$lib/components/ui/button.svelte';
  import { Upload, Film, X } from 'lucide-svelte';
  import { selectValue, inputInt, inputFloat } from '$lib/dom-helpers';

  type Props = {
    file?: File | null;
    onChange: (file: File | null) => void;
    disabled?: boolean;
  };
  let { file = null, onChange, disabled = false }: Props = $props();

  const BYTES_PER_MB = 1024 * 1024;

  function handleDrop(e: DragEvent) {
    e.preventDefault();
    if (disabled) return;
    const f = e.dataTransfer?.files?.[0];
    if (f) onChange(f);
  }
  function handlePick(e: Event) {
    const input = e.currentTarget as HTMLInputElement;
    const f = input.files?.[0];
    if (f) onChange(f);
  }
  function handleChooseFile(e: MouseEvent) {
    e.preventDefault();
    (e.currentTarget as HTMLElement).parentElement?.querySelector('input')?.click();
  }
  function clear() {
    onChange(null);
  }
</script>

<div
  class="flex flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed border-border bg-muted/30 p-6 text-center transition-colors hover:bg-muted/50"
  ondragover={(e: DragEvent) => e.preventDefault()}
  ondrop={handleDrop}
  role="region"
  aria-label="video upload"
>
  {#if file}
    <div class="flex items-center gap-2 text-sm">
      <Film class="size-5 text-primary" />
      <span class="font-mono text-foreground">{file.name}</span>
      <span class="text-muted-foreground">({(file.size / BYTES_PER_MB).toFixed(1)} MB)</span>
      <Button size="icon" variant="ghost" onclick={clear} disabled={disabled} aria-label="remove file">
        <X />
      </Button>
    </div>
  {:else}
    <Upload class="size-8 text-muted-foreground" />
    <p class="text-sm text-muted-foreground">Drag a video file here, or</p>
    <label class="cursor-pointer">
      <Button variant="outline" size="sm" {disabled} type="button" onclick={handleChooseFile}>
        Choose file
      </Button>
      <input type="file" accept="video/*" class="hidden" onchange={handlePick} {disabled} />
    </label>
  {/if}
</div>
