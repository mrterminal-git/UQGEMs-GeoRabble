import type { Ward } from './types';

export const NO_TRANSIT_STOPS_LABEL = 'No transit stops';

export function getRegionDisplayName(
	region: Pick<Ward, 'name' | 'stop_count'> | undefined,
	fallback = ''
): string {
	if (!region) return fallback;
	return region.stop_count === 0 ? NO_TRANSIT_STOPS_LABEL : region.name || fallback;
}
