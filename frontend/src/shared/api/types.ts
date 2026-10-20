export type BBoxTuple = [west: number, south: number, east: number, north: number];

export type QueryParams = Record<string, string | number | boolean | undefined>;

export interface ApiErrorBody {
  detail?: string | { msg: string }[];
}
