<script lang="ts">
	import { SvelteMap } from 'svelte/reactivity';
	import type { ConnectivityScore, Ward, RegionType } from '../types';
	import { getRegionDisplayName } from '../region-display';

	interface Props {
		connectivityScores: ConnectivityScore[];
		wards: Ward[];
		selectedConnectedWardId: string | null;
		hoveredConnectedWardId: string | null;
		regionType: RegionType;
		onSelectConnectedWard: (wardId: string) => void;
		onHoverConnectedWard: (wardId: string | null) => void;
	}

	let {
		connectivityScores,
		wards,
		selectedConnectedWardId,
		hoveredConnectedWardId,
		regionType,
		onSelectConnectedWard,
		onHoverConnectedWard
	}: Props = $props();

	const INITIAL_DISPLAY_COUNT = 100;
	let showAll = $state(false);
	const rowElements = new SvelteMap<string, HTMLButtonElement>();
	let noStopsRow = $state<HTMLDivElement>();

	const wardMap = $derived(new Map(wards.map((w) => [w.id, w])));
	const scoresWithStops = $derived(
		connectivityScores.filter((score) => wardMap.get(score.wardId)?.stop_count !== 0)
	);
	const hasNoStopResults = $derived(
		connectivityScores.some((score) => wardMap.get(score.wardId)?.stop_count === 0)
	);
	const isNoStopsRowHovered = $derived(
		hoveredConnectedWardId !== null &&
			wardMap.get(hoveredConnectedWardId)?.stop_count === 0 &&
			hasNoStopResults
	);

	const displayedScores = $derived(
		showAll || scoresWithStops.length <= INITIAL_DISPLAY_COUNT
			? scoresWithStops
			: scoresWithStops.slice(0, INITIAL_DISPLAY_COUNT)
	);

	const hasMore = $derived(scoresWithStops.length > INITIAL_DISPLAY_COUNT && !showAll);

	function registerRow(node: HTMLButtonElement, regionId: string) {
		rowElements.set(regionId, node);
		return {
			destroy() {
				if (rowElements.get(regionId) === node) {
					rowElements.delete(regionId);
				}
			}
		};
	}

	$effect(() => {
		const regionId = hoveredConnectedWardId;
		if (!regionId) return;
		let frame: number;

		if (wardMap.get(regionId)?.stop_count === 0) {
			if (!hasNoStopResults) return;
			frame = requestAnimationFrame(() => {
				noStopsRow?.scrollIntoView({ block: 'nearest' });
			});
			return () => cancelAnimationFrame(frame);
		}

		const resultIndex = scoresWithStops.findIndex((score) => score.wardId === regionId);
		if (resultIndex < 0) return;

		if (resultIndex >= INITIAL_DISPLAY_COUNT) {
			showAll = true;
		}

		frame = requestAnimationFrame(() => {
			rowElements.get(regionId)?.scrollIntoView({ block: 'nearest' });
		});
		return () => cancelAnimationFrame(frame);
	});

	const OPERATIONAL_HOURS = 16;
	function formatWaitTime(score: number): string {
		const tripsPerHour = score / OPERATIONAL_HOURS;
		if (tripsPerHour <= 0) return '–';
		const rawMinutes = 60 / tripsPerHour;
		if (rawMinutes > 0 && rawMinutes < 5) {
			const rounded = Math.round(rawMinutes * 2) / 2;
			return `${Math.max(0.5, rounded)} min`;
		}
		return `${Math.max(1, Math.round(rawMinutes))} min`;
	}
</script>

<div class="p-4 flex-1 overflow-y-auto">
	{#if connectivityScores.length === 0}
		<div
			class="text-sm text-black"
			style="font-family: ui-sans-serif, system-ui, sans-serif; opacity: 0.6; padding: 8px;"
		>
			No frequent and direct transit access.
		</div>
	{:else}
		<div class="flex items-center justify-between mb-3">
			<p
				class="font-semibold text-sm text-black"
				style="font-family: ui-sans-serif, system-ui, sans-serif;"
			>
				Most accessible {regionType === 'wards' ? 'council electorates' : 'areas'}
			</p>
			<span
				class="text-xs text-black"
				style="opacity: 0.4; font-size: 9px; font-family: ui-sans-serif, system-ui, sans-serif;"
			>
				interval/headway · no. of trips
			</span>
		</div>
		<div class="space-y-1">
			{#each displayedScores as score (score.wardId)}
				<button
					use:registerRow={score.wardId}
					onclick={() => onSelectConnectedWard(score.wardId)}
					onmouseenter={() => onHoverConnectedWard(score.wardId)}
					onmouseleave={() => onHoverConnectedWard(null)}
					class="w-full text-left rounded transition-colors"
					style="padding: 8px; font-family: ui-sans-serif, system-ui, sans-serif; cursor: pointer; {selectedConnectedWardId ===
					score.wardId
						? 'background-color: rgb(229, 229, 229); border-left: 4px solid rgb(37, 99, 235);'
						: hoveredConnectedWardId === score.wardId
							? 'background-color: rgb(219, 234, 254); border-left: 4px solid rgb(37, 99, 235);'
							: 'background-color: rgb(250, 250, 250);'}"
				>
					<div class="flex items-center justify-between">
						<span class="text-sm text-black" style="font-size: 14px;">
							{getRegionDisplayName(wardMap.get(score.wardId), score.wardId)}
						</span>
						<div class="flex flex-col items-end">
							<span class="text-xs text-black" style="opacity: 0.6; font-size: 12px;"
								>{formatWaitTime(score.score)} ({Math.round(score.score)} trips)</span
							>
						</div>
					</div>
				</button>
			{/each}
			{#if hasMore}
				<button
					onclick={() => (showAll = true)}
					class="w-full text-center rounded transition-colors text-sm font-medium mt-2"
					style="padding: 12px; background-color: rgb(245, 245, 245); color: rgb(0, 0, 0); font-family: ui-sans-serif, system-ui, sans-serif; border-radius: 4px;"
					onmouseenter={(e) => (e.currentTarget.style.backgroundColor = 'rgb(229, 229, 229)')}
					onmouseleave={(e) => (e.currentTarget.style.backgroundColor = 'rgb(245, 245, 245)')}
				>
					Show all {scoresWithStops.length}
					{regionType === 'wards' ? 'council electorates' : 'areas'}
				</button>
			{/if}
			{#if hasNoStopResults}
				<div
					bind:this={noStopsRow}
					class="w-full rounded text-left text-sm text-black transition-colors"
					style="padding: 8px; font-family: ui-sans-serif, system-ui, sans-serif; {isNoStopsRowHovered
						? 'background-color: rgb(219, 234, 254); border-left: 4px solid rgb(37, 99, 235);'
						: 'background-color: rgb(250, 250, 250);'}"
					role="status"
				>
					No transit stops
				</div>
			{/if}
		</div>
	{/if}
</div>
