<script lang="ts">
  import { page } from '$app/state';
  import Button from '$lib/components/ui/button.svelte';
  import ObjectMemoryViewer from '$lib/components/object-memory-viewer.svelte';
  import ThemeToggle from '$lib/components/ui/theme-toggle.svelte';
  import { ArrowLeft } from 'lucide-svelte';

  const analysis_id = $derived(String(page.params.analysis_id ?? ''));
</script>

<div class="mx-auto flex h-dvh w-full max-w-7xl flex-col gap-3 p-4">
  <header class="flex items-center justify-between">
    <div>
      <h1 class="text-lg font-semibold">Object Memory</h1>
      <p class="text-xs text-muted-foreground">Analysis <span class="font-mono">{analysis_id}</span></p>
    </div>
    <div class="flex items-center gap-2">
      <ThemeToggle showLabel />
      <Button href="/" variant="outline" size="sm"><ArrowLeft /> Back to analysis</Button>
    </div>
  </header>

  {#if analysis_id}
    <ObjectMemoryViewer analysisId={analysis_id} />
  {/if}
</div>
