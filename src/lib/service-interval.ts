const OPERATIONAL_MINUTES = 16 * 60;

export function formatEstimatedAverageInterval(serviceCount: number): string {
	if (!Number.isFinite(serviceCount) || serviceCount <= 0) return 'No direct service';

	const rawMinutes = OPERATIONAL_MINUTES / serviceCount;
	if (rawMinutes > OPERATIONAL_MINUTES) return 'Less than once per service day';
	if (rawMinutes === OPERATIONAL_MINUTES) return 'About once per service day';

	if (rawMinutes < 60) {
		const roundedMinutes = rawMinutes < 5 ? Math.round(rawMinutes * 2) / 2 : Math.round(rawMinutes);
		return `~${Math.max(0.5, roundedMinutes)} min`;
	}

	const roundedMinutes = Math.max(60, Math.round(rawMinutes / 5) * 5);
	const hours = Math.floor(roundedMinutes / 60);
	const minutes = roundedMinutes % 60;
	const hourLabel = `${hours} hr`;

	return minutes === 0 ? `~${hourLabel}` : `~${hourLabel} ${minutes} min`;
}
