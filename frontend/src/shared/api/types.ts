export type QueryParams = Record<string, string | number | boolean | undefined>;

export type Position = [lng: number, lat: number];

export interface ApiErrorBody {
  code: string;
  message: string;
  field?: string;
}
