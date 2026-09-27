<script lang="ts">
	import type { CityCode } from '../cityConfigs';
	import { cityConfigs } from '../cityConfigs';

	interface Props {
		currentCity: CityCode;
		onCityChange: (city: CityCode) => void;
	}

	let { currentCity, onCityChange }: Props = $props();
	let isOpen = $state(false);

	function handleCitySelect(city: CityCode) {
		onCityChange(city);
		isOpen = false;
	}

	function handleClickOutside(event: MouseEvent) {
		const target = event.target as HTMLElement;
		if (!target.closest('.city-selector')) {
			isOpen = false;
		}
	}

	$effect(() => {
		if (isOpen) {
			document.addEventListener('click', handleClickOutside);
			return () => {
				document.removeEventListener('click', handleClickOutside);
			};
		}
	});
</script>

<div class="city-selector relative inline-block">
	<button
		type="button"
		onclick={() => (isOpen = !isOpen)}
		title="Change city"
		class="cursor-pointer inline-flex items-center rounded bg-black h-7 px-2 text-white hover:bg-black/80 transition-colors {isOpen
			? 'bg-black/80'
			: ''}"
		style="font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace; letter-spacing: 0.35px;"
	>
		{cityConfigs[currentCity].code.toUpperCase()}
	</button>

	{#if isOpen}
		<div
			class="absolute left-0 top-full mt-1 bg-white border border-gray-300 rounded shadow-lg z-50 min-w-[120px]"
			style="font-family: ui-sans-serif, system-ui, sans-serif;"
		>
			{#each Object.values(cityConfigs) as city}
				<button
					type="button"
					onclick={() => handleCitySelect(city.code)}
					class="w-full text-left px-4 py-2 text-sm hover:bg-gray-100 transition-colors {currentCity ===
					city.code
						? ''
						: 'font-medium'}"
				>
					{city.name}
				</button>
			{/each}
		</div>
	{/if}
</div>
