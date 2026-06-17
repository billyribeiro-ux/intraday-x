// Time helpers for chart data. The backend already sends epoch seconds; ECharts
// time axes accept epoch milliseconds or a Date, so we mostly pass values
// through. This module keeps the venue-offset helper available for later
// timezone-aware rendering.

/** NY is UTC-4 during EDT (most of the trading year). DST-exact handling is a
 *  later refinement; for the scaffold we expose the offset explicitly. */
export const NY_OFFSET_MINUTES = -240;

/** Convert an ISO string / Date / epoch-ms to epoch seconds, shifted by
 *  `offsetMinutes` so the axis can read in venue-local time when needed. */
export function toChartTime(
	value: string | number | Date,
	offsetMinutes = 0
): number {
	const ms = value instanceof Date ? value.getTime() : new Date(value).getTime();
	return Math.floor(ms / 1000 + offsetMinutes * 60);
}

/** Convert a timeframe label to its length in seconds for live bar bucketing. */
export function timeframeToSeconds(tf: string): number {
	const m = tf.match(/^(\d+)?(m|h|d|w|mo|y)$/);
	if (!m) return 60;
	const n = m[1] ? parseInt(m[1], 10) : 1;
	switch (m[2]) {
		case 'm':
			return n * 60;
		case 'h':
			return n * 3600;
		case 'd':
			return n * 86400;
		case 'w':
			return n * 86400 * 7;
		case 'mo':
			return n * 86400 * 30;
		case 'y':
			return n * 86400 * 365;
	}
	return 60;
}
