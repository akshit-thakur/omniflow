/**
 * Media API hooks
 * Endpoints: /media
 */

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";

export type MediaType =
  | "book"
  | "movie"
  | "tv_show"
  | "video_game"
  | "podcast"
  | "documentary"
  | "anime"
  | "manga"
  | "music_album"
  | "audiobook";

export type MediaStatus =
  | "to_watch"
  | "watching"
  | "completed"
  | "on_hold"
  | "dropped"
  | "plan_to_watch";

export interface MediaItem {
  id: number;
  title: string;
  media_type: MediaType;
  status: MediaStatus;
  author_creator: string | null;
  release_year: number | null;
  genre: string | null;
  progress_current: number;
  progress_total: number | null;
  is_favorite: boolean;
  rating: number | null;
  notes: string | null;
  review: string | null;
  completion_date: string | null;
  created_at: string;
  updated_at: string;
}

export interface MediaCreateInput {
  title: string;
  media_type: MediaType;
  genre?: string;
  status?: MediaStatus;
  author_creator?: string;
  release_year?: number;
  progress_current?: number;
  progress_total?: number;
  is_favorite?: boolean;
  notes?: string;
}

export type MediaUpdateInput = Partial<
  Pick<
    MediaItem,
    | "title"
    | "media_type"
    | "genre"
    | "status"
    | "author_creator"
    | "release_year"
    | "progress_current"
    | "progress_total"
    | "is_favorite"
    | "rating"
    | "notes"
    | "review"
  >
>;

export const useMedia = () =>
  useQuery<MediaItem[]>({
    queryKey: ["media"],
    queryFn: () => api.get("/media/"),
  });

export const useCreateMedia = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: MediaCreateInput) => api.post<MediaItem>("/media/", data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["media"] }),
  });
};

export const useUpdateMedia = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: MediaUpdateInput }) =>
      api.put<MediaItem>(`/media/${id}/`, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["media"] }),
  });
};

export const useDeleteMedia = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.delete(`/media/${id}/`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["media"] }),
  });
};

export const useBulkImportMedia = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (items: MediaCreateInput[]) =>
      api.post<{ items: MediaItem[]; created: number }>("/media/bulk", { items }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["media"] }),
  });
};
