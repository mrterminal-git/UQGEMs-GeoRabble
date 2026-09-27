<script lang="ts">
	import type { Route, RegionType } from '../types';

	interface Props {
		connectingRoutes: Route[];
		regionType: RegionType;
		selectedRouteId: string | null;
		onSelectRoute: (routeId: string | null) => void;
	}

	let { connectingRoutes, regionType, selectedRouteId, onSelectRoute }: Props = $props();

	const OPERATIONAL_HOURS = 16;
	function formatWaitTime(count: number): string {
		const tripsPerHour = count / OPERATIONAL_HOURS;
		if (tripsPerHour <= 0) return '–';
		const rawMinutes = 60 / tripsPerHour;
		if (rawMinutes > 0 && rawMinutes < 5) {
			const rounded = Math.round(rawMinutes * 2) / 2;
			return `${Math.max(0.5, rounded)} min`;
		}
		return `${Math.max(1, Math.round(rawMinutes))} min`;
	}
</script>

<div class="p-4 flex-1 overflow-y-auto" style="background-color: rgb(229, 229, 229);">
	{#if connectingRoutes.length === 0}
		<p
			class="text-sm"
			style="color: rgb(0, 0, 0); opacity: 0.6; font-family: ui-sans-serif, system-ui, sans-serif;"
		>
			No routes found connecting these {regionType === 'wards' ? 'wards' : 'areas'}.
		</p>
	{:else}
		<div class="space-y-3">
			{#each connectingRoutes as route}
				<button
					onclick={() => onSelectRoute(selectedRouteId === route.route_id ? null : route.route_id)}
					class="w-full text-left rounded p-3 transition-colors"
					style="border-radius: 4px; cursor: pointer; {selectedRouteId === route.route_id
						? 'background-color: rgb(219, 234, 254); border-left: 4px solid rgb(37, 99, 235);'
						: 'background-color: rgb(255, 255, 255);'}"
				>
					<h3
						class="mb-2"
						style="font-family: ui-sans-serif, system-ui, sans-serif; font-size: 14px;"
					>
						{route.route_short_name || route.route_long_name} ({route.route_long_name})
					</h3>
					{#if route.trip_count !== undefined && route.trip_count !== null}
						<div
							class="text-xs"
							style="color: rgb(0, 0, 0); opacity: 0.6; font-family: ui-sans-serif, system-ui, sans-serif;"
						>
							<p>{formatWaitTime(route.trip_count)} ({route.trip_count} trips)</p>
						</div>
					{/if}
				</button>
			{/each}
		</div>
	{/if}
</div>
