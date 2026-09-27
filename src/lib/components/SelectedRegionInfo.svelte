<script lang="ts">
	interface Props {
		selectedRegion: string;
	}

	let { selectedRegion }: Props = $props();
</script>

<div class="px-4">
	<h2
		class="font-semibold text-lg text-black"
		style="font-family: ui-sans-serif, system-ui, sans-serif;"
	>
		{selectedRegion}
	</h2>
</div>
