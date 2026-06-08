// Lightweight Charts has NO native timezone support — it treats every time as a
// UTC epoch and renders it literally. To show intraday bars in the venue's local
// time we shift the epoch by the venue offset before handing it to the chart.
// (See docs/AI_LANDMINES.md.)

import type { UTCTimestamp } from 'lightweight-charts';

/** NY is UTC-4 during EDT (most of the trading year). DST-exact handling is a
 *  later refinement; for the scaffold we expose the offset explicitly. */
export const NY_OFFSET_MINUTES = -240;

/** Convert an ISO string / Date / epoch-ms to a Lightweight Charts time,
 *  shifted by `offsetMinutes` so the axis reads in venue-local time. */
export function toChartTime(
	value: string | number | Date,
	offsetMinutes = 0
): UTCTimestamp {
	const ms = value instanceof Date ? value.getTime() : new Date(value).getTime();
	return Math.floor(ms / 1000 + offsetMinutes * 60) as UTCTimestamp;
}
