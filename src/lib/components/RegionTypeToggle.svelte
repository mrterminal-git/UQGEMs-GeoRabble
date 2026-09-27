<script lang="ts">
	import type { RegionType } from '../types';

	interface Props {
		regionType: RegionType;
		supportedRegions: RegionType[];
		onSwitch: (type: RegionType) => void;
	}

	let { regionType, supportedRegions, onSwitch }: Props = $props();

	const regionLabels: Record<RegionType, string> = {
		hexagons: 'Areas',
		wards: 'Wards'
	};
</script>

<div class="mt-4">
	<div
		class="flex rounded overflow-hidden"
		style="border: 1px solid oklch(0.872 0.01 258.338); border-radius: 4px;"
	>
		{#each supportedRegions as type}
			<button
				onclick={() => onSwitch(type)}
				class="flex-1 text-sm font-medium transition-colors"
				style="padding: 8px; font-family: ui-sans-serif, system-ui, sans-serif; {regionType === type
					? 'background-color: rgb(91, 91, 91); color: rgb(255, 255, 255);'
					: 'background-color: rgb(255, 255, 255); color: rgb(0, 0, 0);'}"
				onmouseenter={(e) => {
					if (regionType !== type) e.currentTarget.style.backgroundColor = 'rgb(245, 245, 245)';
				}}
				onmouseleave={(e) => {
					if (regionType !== type) e.currentTarget.style.backgroundColor = 'rgb(255, 255, 255)';
				}}
			>
				{regionLabels[type]}
			</button>
		{/each}
	</div>
</div>
