/**
 * Meal Plans API hooks
 * Endpoints: /api/meal-plans
 */

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";

export interface MealPlan {
  id: number;
  date: string;
  meal_type: "breakfast" | "lunch" | "dinner" | "snack";
  recipe_id?: number;
  recipe_name?: string;
  notes?: string;
}

export const useMealPlans = () =>
  useQuery<MealPlan[]>({
    queryKey: ["meal-plans"],
    queryFn: () => api.get("/meal-plans"),
  });

export const useCreateMealPlan = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: {
      date: string;
      meal_type: string;
      recipe_id?: number;
      notes?: string;
    }) => api.post("/meal-plans", data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["meal-plans"] }),
  });
};

export const useDeleteMealPlan = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.delete(`/meal-plans/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["meal-plans"] }),
  });
};

export const useUpdateMealPlan = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: {
      id: number;
      data: { date?: string; meal_type?: string; recipe_id?: number | null; notes?: string | null };
    }) => api.put(`/meal-plans/${id}`, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["meal-plans"] }),
  });
};

export interface MealBatchItem {
  id?: number;
  date: string;
  meal_type: string;
  recipe_id?: number | null;
  notes?: string | null;
}

export const useSaveMealBatch = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { items: MealBatchItem[]; delete_ids: number[] }) =>
      api.post('/meal-plans/batch', data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["meal-plans"] }),
  });
};
